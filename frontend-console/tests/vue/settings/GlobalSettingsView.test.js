/**
 * GlobalSettingsView 组件测试 — 对应原 globalSettingsView.test.js，并覆盖保存与迁移流程。
 * bridge 替身通过 setBridgeOverrides 注入（生产代码不 import Mock）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { mount } from "@vue/test-utils"
import GlobalSettingsView from "../../../vue/views/settings/GlobalSettingsView.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { ISLAND_LEAVE_GUARD } from "../../../vue/mountIsland.js"

function makeProps(overrides = {}) {
  return {
    llmDefaults: { base_url: "https://api.deepseek.com", model: "deepseek-v4-flash" },
    authorPrefs: {},
    templates: [],
    projectsUsingDefaults: { items: [], total: 0, truncated: false },
    ...overrides,
  }
}

function overrideProjectId(projectId) {
  const listeners = []
  setBridgeOverrides({
    state: { currentProjectId: projectId },
    onStateChange: (listener) => {
      listeners.push(listener)
      return () => listeners.splice(listeners.indexOf(listener), 1)
    },
  })
  return {
    fireProjectId(value) {
      listeners.forEach((listener) => listener("currentProjectId", value, null))
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("渲染（原 vanilla render 契约）", () => {
  it("渲染各区块标题与禁用态的进入项目按钮", () => {
    overrideProjectId(null)
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })
    const text = wrapper.text()
    expect(text).toContain("全局设置")
    expect(text).toContain("owner: local")
    expect(text).toContain("LLM 全局默认")
    expect(text).toContain("作者偏好全局默认")
    expect(text).toContain("引用此默认的项目")
    expect(text).toContain("本地迁移")
    expect(wrapper.find("#llm-base-url").element.value).toBe("https://api.deepseek.com")
    expect(wrapper.find("#llm-model").element.value).toBe("deepseek-v4-flash")

    const button = wrapper.find("#goto-recent-project-btn")
    expect(button.text()).toContain("进入当前项目")
    expect(button.attributes("disabled")).toBeDefined()
  })

  it("有当前项目时按钮可用，点击跳项目设置", async () => {
    overrideProjectId("abc-123")
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })
    const button = wrapper.find("#goto-recent-project-btn")
    expect(button.attributes("disabled")).toBeUndefined()
    await button.trigger("click")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("project-settings")
  })

  it("无继承项目时显示空提示；截断时显示省略提示", () => {
    overrideProjectId(null)
    const empty = mount(GlobalSettingsView, { props: makeProps() })
    expect(empty.text()).toContain("没有项目继承全局默认")

    const truncated = mount(GlobalSettingsView, {
      props: makeProps({
        projectsUsingDefaults: {
          items: [{ project_id: "x", title: "p1" }],
          total: 200,
          truncated: true,
        },
      }),
    })
    expect(truncated.find(".projects-using-list").exists()).toBe(true)
    expect(truncated.text()).toContain("更多项目省略")
  })
})

describe("未保存离开守卫", () => {
  it("修改全局设置后在路由离开前确认", async () => {
    const confirm = vi.fn(() => false)
    setBridgeOverrides({ confirm })
    let guard = null
    const wrapper = mount(GlobalSettingsView, {
      props: makeProps(),
      global: { provide: { [ISLAND_LEAVE_GUARD]: (fn) => { guard = fn } } },
    })
    expect(guard()).toBe(true)
    await wrapper.find("#llm-model").setValue("changed-model")
    expect(guard()).toBe(false)
    expect(confirm).toHaveBeenCalledWith("全局设置有未保存修改，确定放弃并离开吗？")
  })
})

describe("保存 LLM 全局默认", () => {
  it("成功时剥离 Key 字段并提示", async () => {
    overrideProjectId(null)
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })
    await wrapper.find("#global-llm-save").trigger("click")

    expect(globalThis.api.settings.updateGlobalLLMDefaults).toHaveBeenCalledTimes(1)
    const payload = globalThis.api.settings.updateGlobalLLMDefaults.mock.calls[0][0]
    expect(payload.api_key).toBeUndefined()
    expect(payload.clear_api_key).toBeUndefined()
    expect(payload.base_url).toBe("https://api.deepseek.com")
    expect(globalThis.toast).toHaveBeenCalledWith("LLM 全局默认已保存", "success")
  })

  it("数值越界时仅警告不调接口", async () => {
    overrideProjectId(null)
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })
    await wrapper.find("#llm-timeout").setValue("99999")
    await wrapper.find("#global-llm-save").trigger("click")

    expect(globalThis.api.settings.updateGlobalLLMDefaults).not.toHaveBeenCalled()
    expect(globalThis.toast).toHaveBeenCalledWith(expect.stringContaining("非法"), "warning")
  })

  it("接口失败时提示并短暂挂错误类", async () => {
    overrideProjectId(null)
    globalThis.api.settings.updateGlobalLLMDefaults.mockRejectedValueOnce(new Error("保存失败"))
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })
    await wrapper.find("#global-llm-save").trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.find("#global-llm-save").classes()).toContain("settings-btn-error")
    })
    expect(globalThis.toast).toHaveBeenCalledWith("保存失败", "error")
  })

  it("保存请求期间的新输入不会被误标为已保存", async () => {
    overrideProjectId(null)
    let resolveSave
    globalThis.api.settings.updateGlobalLLMDefaults.mockImplementationOnce(() => new Promise((resolve) => {
      resolveSave = resolve
    }))
    const confirm = vi.fn(() => false)
    setBridgeOverrides({ confirm })
    let guard = null
    const wrapper = mount(GlobalSettingsView, {
      props: makeProps(),
      global: { provide: { [ISLAND_LEAVE_GUARD]: (fn) => { guard = fn } } },
    })
    await wrapper.find("#llm-model").setValue("submitted-model")
    wrapper.find("#global-llm-save").element.click()
    await vi.waitFor(() => expect(globalThis.api.settings.updateGlobalLLMDefaults).toHaveBeenCalledOnce())
    await wrapper.find("#llm-model").setValue("newer-unsaved-model")

    resolveSave({})
    await vi.waitFor(() => expect(globalThis.toast).toHaveBeenCalledWith("LLM 全局默认已保存", "success"))
    expect(wrapper.find("#llm-model").element.value).toBe("newer-unsaved-model")
    expect(guard()).toBe(false)
  })
})

describe("保存作者偏好", () => {
  it("日更目标越界时拒绝", async () => {
    overrideProjectId(null)
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })
    await wrapper.find("#author-daily-goal").setValue("100001")
    await wrapper.find("#global-author-save").trigger("click")

    expect(globalThis.api.settings.updateGlobalAuthorPrefs).not.toHaveBeenCalled()
    expect(globalThis.toast).toHaveBeenCalledWith("日更目标必须是 0-100000 的整数", "warning")
  })

  it("合法值保存成功", async () => {
    overrideProjectId(null)
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })
    await wrapper.find("#author-daily-goal").setValue("500")
    await wrapper.find("#global-author-save").trigger("click")

    expect(globalThis.api.settings.updateGlobalAuthorPrefs).toHaveBeenCalledWith({
      daily_goal: 500,
      editor_font: "system",
      default_focus_mode: false,
    })
    expect(globalThis.toast).toHaveBeenCalledWith("作者偏好已保存", "success")
  })
})

describe("本地迁移", () => {
  it("迁移 localStorage 旧偏好到后端并清理 key", async () => {
    overrideProjectId(null)
    localStorage.setItem("novel_author_preferences:p9", JSON.stringify({ dailyGoal: 100, defaultFocusMode: true }))
    localStorage.setItem("novel_author_preferences:global", JSON.stringify({ dailyGoal: 1 }))
    // setup.js 默认 getProjectAuthorPrefs 返回全 null → 触发迁移写入
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })
    await wrapper.find("#manual-migrate-btn").trigger("click")
    await vi.waitFor(() => {
      expect(globalThis.api.settings.updateProjectAuthorPrefs).toHaveBeenCalled()
    })

    expect(globalThis.api.settings.updateProjectAuthorPrefs).toHaveBeenCalledWith("p9", {
      daily_goal: 100,
      editor_font: null,
      default_focus_mode: true,
    })
    expect(localStorage.getItem("novel_author_preferences:p9")).toBeNull()
    expect(localStorage.getItem("novel_author_preferences:global")).not.toBeNull()
    expect(globalThis.toast).toHaveBeenCalledWith("已迁移 1 个项目，余 1 个", "success")
  })
})
