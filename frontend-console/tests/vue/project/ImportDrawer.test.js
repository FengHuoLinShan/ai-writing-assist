/**
 * ImportDrawer 组件测试 — 导入抽屉（上传入口、历史渲染、项目联动）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import ImportDrawer from "../../../vue/views/project/components/ImportDrawer.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

function makeState(currentProjectId = "p1", currentProject = { title: "测试项目" }) {
  const listeners = []
  const state = { currentProjectId, currentProject }
  return {
    state,
    onStateChange: (listener) => {
      listeners.push(listener)
      return () => listeners.splice(listeners.indexOf(listener), 1)
    },
    emit(key, value) {
      state[key] = value
      for (const listener of listeners) listener(key, value)
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  globalThis.api.imports.list = vi.fn(async () => ({
    items: [
      {
        id: "r1",
        file_name: "旧稿.txt",
        status: "done",
        imported_chapters: 10,
        total_chapters: 10,
        created_at: "2026-07-01T08:00:00Z",
      },
    ],
  }))
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("ImportDrawer", () => {
  it("有当前项目时渲染表单并加载导入历史", async () => {
    const harness = makeState()
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)
    expect(wrapper.find("#pv-import-file").attributes("disabled")).toBeUndefined()
    expect(wrapper.text()).toContain("当前项目：")
    expect(wrapper.text()).toContain("测试项目")
    await vi.waitFor(() => {
      expect(wrapper.find(".import-list-item").exists()).toBe(true)
    })
    expect(wrapper.find(".project-import-list__item-name").text()).toBe("旧稿.txt")
    expect(wrapper.find(".pill").text()).toBe("完成")
    expect(wrapper.text()).toContain("成功 10 / 共 10 章")
  })

  it("无当前项目时禁用输入并提示先选择项目", () => {
    const harness = makeState(null, null)
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)
    expect(wrapper.find("#pv-import-file").attributes("disabled")).toBeDefined()
    expect(wrapper.find('[data-action="upload-file"]').attributes("disabled")).toBeDefined()
    expect(wrapper.text()).toContain("请先点击项目行选择项目")
    expect(wrapper.text()).toContain("选择项目后查看导入记录。")
    expect(wrapper.text()).not.toContain("暂无导入记录。")
    expect(globalThis.api.imports.list).not.toHaveBeenCalled()
    expect(wrapper.find('label[for="pv-import-file"]').exists()).toBe(true)
    expect(wrapper.find('label[for="pv-import-file"]').text()).toBe("选择文件（支持 txt、epub、html、htm、mobi、azw3，最大 50MB）")
    expect(wrapper.find("#pv-import-file").attributes("accept")).toBe(".txt,.epub,.html,.htm,.mobi,.azw3")
  })

  it("选择文件后导入为新项目 emit 同一 File", async () => {
    const harness = makeState()
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)
    const selectedFile = new File(["正文"], "复用文件.txt", { type: "text/plain" })
    Object.defineProperty(wrapper.find("#pv-import-file").element, "files", {
      configurable: true,
      value: [selectedFile],
    })

    await wrapper.find('[data-action="import"]').trigger("click")

    expect(wrapper.emitted("import-new-project")).toEqual([[selectedFile]])
  })

  it("未选择文件时导入为新项目 emit null，保留父级 chooser 路径", async () => {
    const harness = makeState()
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)

    await wrapper.find('[data-action="import"]').trigger("click")

    expect(wrapper.emitted("import-new-project")).toEqual([[null]])
  })

  it("历史为空时显示暂无导入记录", async () => {
    globalThis.api.imports.list = vi.fn(async () => ({ items: [] }))
    const harness = makeState()
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)
    await vi.waitFor(() => {
      expect(wrapper.find(".project-import-list__empty").exists()).toBe(true)
    })
    expect(wrapper.text()).toContain("暂无导入记录。")
  })

  it("首次加载失败显示固定提示和重试，不泄露诊断或伪装为空记录", async () => {
    globalThis.api.imports.list = vi.fn(async () => {
      throw new Error("diagnostic-marker: connection reset")
    })
    const harness = makeState()
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)

    await vi.waitFor(() => {
      expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    })

    expect(wrapper.text()).toContain("导入记录暂时无法加载，请重试。")
    expect(wrapper.text()).not.toContain("diagnostic-marker")
    expect(wrapper.text()).not.toContain("暂无导入记录。")
    expect(wrapper.find('[data-action="retry-import-history"]').text()).toBe("重试")
    expect(wrapper.find("#import-list-body").attributes("aria-busy")).toBe("false")
  })

  it("重试期间保留失败上下文并在成功后显示真实空记录", async () => {
    let resolveRetry
    globalThis.api.imports.list = vi.fn()
      .mockRejectedValueOnce(new Error("initial diagnostic"))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRetry = resolve }))
    const harness = makeState()
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)

    await vi.waitFor(() => expect(wrapper.find('[data-action="retry-import-history"]').exists()).toBe(true))
    await wrapper.find('[data-action="retry-import-history"]').trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.find('[data-action="retry-import-history"]').attributes("disabled")).toBeDefined()
    })
    expect(wrapper.find('[data-action="retry-import-history"]').text()).toBe("正在重试...")
    expect(wrapper.text()).toContain("导入记录暂时无法加载，请重试。")

    resolveRetry({ items: [] })
    await vi.waitFor(() => {
      expect(wrapper.find('[role="alert"]').exists()).toBe(false)
      expect(wrapper.find(".project-import-list__empty").exists()).toBe(true)
    })
    expect(wrapper.text()).toContain("暂无导入记录。")
  })

  it("同一项目上传后的刷新失败保留上次成功记录", async () => {
    let rejectRefresh
    globalThis.api.imports.list = vi.fn()
      .mockResolvedValueOnce({
        items: [{ id: "last-known", file_name: "上次成功.txt", status: "done" }],
      })
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectRefresh = reject }))
    globalThis.api.imports.uploadFile = vi.fn(async () => ({ total_chapters: 0, imported_chapters: 0 }))
    const harness = makeState()
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)

    await vi.waitFor(() => expect(wrapper.text()).toContain("上次成功.txt"))
    Object.defineProperty(wrapper.find("#pv-import-file").element, "files", {
      configurable: true,
      value: [{ name: "刷新触发.txt", size: 1 }],
    })
    await wrapper.find('[data-action="upload-file"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.text()).toContain("正在刷新导入记录..."))
    expect(wrapper.text()).toContain("上次成功.txt")

    rejectRefresh(new Error("refresh diagnostic"))
    await vi.waitFor(() => expect(wrapper.find('[role="alert"]').exists()).toBe(true))
    expect(wrapper.text()).toContain("导入记录刷新失败，当前显示上次加载的内容。")
    expect(wrapper.text()).toContain("上次成功.txt")
    expect(wrapper.text()).not.toContain("refresh diagnostic")
  })

  it("只为失败导入显示经转义的失败原因", async () => {
    globalThis.api.imports.list = vi.fn(async () => ({
      items: [
        {
          id: "failed",
          file_name: "空文件.txt",
          status: "failed",
          error_message: "文件中未检测到有效章节",
        },
        {
          id: "escaped",
          file_name: "异常文件.txt",
          status: "failed",
          error_message: "<img src=x onerror=alert(1)>",
        },
        {
          id: "done",
          file_name: "已完成.txt",
          status: "done",
          error_message: "完成记录不应显示的错误",
        },
      ],
    }))
    const harness = makeState()
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)

    await vi.waitFor(() => {
      expect(wrapper.find(".project-import-list__item-error").exists()).toBe(true)
    })

    expect(wrapper.find(".project-import-list__item-error").text()).toContain("失败原因：文件中未检测到有效章节")
    expect(wrapper.findAll(".project-import-list__item-error")).toHaveLength(2)
    expect(wrapper.find("img").exists()).toBe(false)
    expect(wrapper.text()).toContain("<img src=x onerror=alert(1)>")
    expect(wrapper.text()).not.toContain("完成记录不应显示的错误")
  })

  it("失败记录没有可用原因时显示作者可读回退", async () => {
    globalThis.api.imports.list = vi.fn(async () => ({
      items: [{ id: "failed", file_name: "未知文件.txt", status: "failed", error_message: "   " }],
    }))
    const harness = makeState()
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain("导入失败，请检查文件后重试。")
    })
  })

  it("项目切换后丢弃旧项目晚到的导入历史", async () => {
    let resolveOld
    let resolveCurrent
    globalThis.api.imports.list = vi.fn(({ novel_id: projectId }) => new Promise((resolve) => {
      if (projectId === "p-old") resolveOld = resolve
      if (projectId === "p-current") resolveCurrent = resolve
    }))
    const harness = makeState("p-old", { title: "旧项目" })
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)
    await vi.waitFor(() => expect(globalThis.api.imports.list).toHaveBeenCalledWith({ novel_id: "p-old" }))

    harness.emit("currentProjectId", "p-current")
    harness.emit("currentProject", { title: "当前项目" })
    await vi.waitFor(() => expect(globalThis.api.imports.list).toHaveBeenCalledWith({ novel_id: "p-current" }))
    resolveCurrent({ items: [{ id: "current", file_name: "当前稿.txt", status: "done" }] })
    await vi.waitFor(() => expect(wrapper.text()).toContain("当前稿.txt"))

    resolveOld({ items: [{ id: "old", file_name: "旧项目稿.txt", status: "done" }] })
    await flushPromises()
    expect(wrapper.text()).toContain("当前稿.txt")
    expect(wrapper.text()).not.toContain("旧项目稿.txt")
  })

  it("切换项目时立即清空已经显示的旧项目记录", async () => {
    let resolveCurrent
    globalThis.api.imports.list = vi.fn(({ novel_id: projectId }) => {
      if (projectId === "p-old") {
        return Promise.resolve({ items: [{ id: "old", file_name: "旧项目稿.txt", status: "done" }] })
      }
      return new Promise((resolve) => { resolveCurrent = resolve })
    })
    const harness = makeState("p-old", { title: "旧项目" })
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)
    await vi.waitFor(() => expect(wrapper.text()).toContain("旧项目稿.txt"))

    harness.emit("currentProjectId", "p-current")
    harness.emit("currentProject", { title: "当前项目" })
    await vi.waitFor(() => expect(globalThis.api.imports.list).toHaveBeenCalledWith({ novel_id: "p-current" }))
    expect(wrapper.text()).not.toContain("旧项目稿.txt")

    resolveCurrent({ items: [{ id: "current", file_name: "当前项目稿.txt", status: "done" }] })
    await vi.waitFor(() => expect(wrapper.text()).toContain("当前项目稿.txt"))
  })

  it("未选择文件点击上传给出警告", async () => {
    const harness = makeState()
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)
    await wrapper.find('[data-action="upload-file"]').trigger("click")
    expect(globalThis.toast).toHaveBeenCalledWith("请先选择文件", "warning")
    expect(globalThis.api.imports.uploadFile).not.toHaveBeenCalled()
  })
})
