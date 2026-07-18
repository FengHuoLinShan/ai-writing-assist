/**
 * ImportDrawer 组件测试 — 导入抽屉（上传入口、历史渲染、项目联动）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { mount } from "@vue/test-utils"
import ImportDrawer from "../../../vue/views/project/components/ImportDrawer.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

function makeState(currentProjectId = "p1", currentProject = { title: "测试项目" }) {
  const listeners = []
  return {
    state: { currentProjectId, currentProject },
    onStateChange: (listener) => {
      listeners.push(listener)
      return () => listeners.splice(listeners.indexOf(listener), 1)
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

  it("未选择文件点击上传给出警告", async () => {
    const harness = makeState()
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)
    await wrapper.find('[data-action="upload-file"]').trigger("click")
    expect(globalThis.toast).toHaveBeenCalledWith("请先选择文件", "warning")
    expect(globalThis.api.imports.uploadFile).not.toHaveBeenCalled()
  })
})
