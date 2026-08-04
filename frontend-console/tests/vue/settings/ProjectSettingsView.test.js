import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import ProjectSettingsView from "../../../vue/views/settings/ProjectSettingsView.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { ISLAND_LEAVE_GUARD } from "../../../vue/mountIsland.js"
import { projectSettingsSession } from "../../../vue/views/settings/projectSettingsSession.js"

function makeEffectiveLLM(overrides = {}) {
  return {
    provider_id: { value: "deepseek", source: "global" },
    label: { value: "DeepSeek", source: "global" },
    model: { value: "deepseek-v4-flash", source: "global" },
    api_key_configured: { value: false, source: "unset" },
    deep_import: { value: null, source: "system" },
    ...overrides,
  }
}

function makeEffectivePrefs(overrides = {}) {
  return {
    daily_goal: { value: null, source: "system" },
    editor_font: { value: "system", source: "system" },
    default_focus_mode: { value: false, source: "system" },
    ...overrides,
  }
}

function makeProps(overrides = {}) {
  return {
    projectId: "p1",
    projectTitle: "测试项目",
    effectiveLLM: makeEffectiveLLM(),
    effectivePrefs: makeEffectivePrefs(),
    ...overrides,
  }
}

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

beforeEach(() => {
  vi.clearAllMocks()
  projectSettingsSession.tab = "deep"
  globalThis.api.settings.getEffectiveLLMSettings.mockImplementation(
    async () => makeEffectiveLLM(),
  )
  globalThis.api.settings.getEffectiveAuthorPrefs.mockImplementation(
    async () => makeEffectivePrefs(),
  )
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("结构与导航", () => {
  it("无项目显示空态并返回账户设置", async () => {
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps({
        projectId: null,
        effectiveLLM: null,
        effectivePrefs: null,
      }),
    })
    expect(wrapper.text()).toContain("请先进入项目")
    await wrapper.find("#project-settings-goto-global").trigger("click")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("settings")
  })

  it("只保留深度导入和作者偏好，模型连接跳账户设置", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    const tabs = wrapper.findAll(".settings-tab-nav .tab-btn")
    expect(tabs.map((item) => item.text())).toEqual(["深度导入", "作者偏好"])
    expect(wrapper.text()).toContain("当前模型：DeepSeek · deepseek-v4-flash · 未连接")
    expect(wrapper.find("#llm-model").exists()).toBe(false)

    await wrapper.find("#project-settings-goto-global").trigger("click")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("settings")
  })

  it("Tab 选择在页面往返间保留", async () => {
    const first = mount(ProjectSettingsView, { props: makeProps() })
    await first.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    expect(first.find(".author-prefs-tab").exists()).toBe(true)
    first.unmount()

    const second = mount(ProjectSettingsView, { props: makeProps() })
    expect(second.find(".author-prefs-tab").exists()).toBe(true)
    expect(second.findAll(".settings-tab-nav .tab-btn")[1].attributes("aria-selected"))
      .toBe("true")
  })

  it("Tab 提供稳定关联并用键盘选择、回焦与持久化", async () => {
    const wrapper = mount(ProjectSettingsView, {
      attachTo: document.body,
      props: makeProps(),
    })
    const tabs = wrapper.findAll(".settings-tab-nav .tab-btn")
    const panel = wrapper.get("#project-settings-tab-panel")
    expect(tabs[0].attributes("id")).toBe("project-settings-tab-deep")
    expect(tabs[0].attributes("aria-controls")).toBe("project-settings-tab-panel")
    expect(tabs[0].attributes("tabindex")).toBe("0")
    expect(tabs[1].attributes("tabindex")).toBe("-1")
    expect(panel.attributes("aria-labelledby")).toBe("project-settings-tab-deep")

    tabs[0].element.focus()
    await tabs[0].trigger("keydown", { key: "ArrowRight" })
    await vi.waitFor(() => expect(document.activeElement).toBe(tabs[1].element))
    expect(tabs[1].attributes("aria-selected")).toBe("true")
    expect(panel.attributes("aria-labelledby")).toBe("project-settings-tab-author")
    expect(projectSettingsSession.tab).toBe("author")

    await tabs[1].trigger("keydown", { key: "Home" })
    await vi.waitFor(() => expect(document.activeElement).toBe(tabs[0].element))
    expect(tabs[0].attributes("aria-selected")).toBe("true")
    wrapper.unmount()
  })

  it("面板在数据未就绪和保存期间公开真实忙碌状态", async () => {
    const pending = mount(ProjectSettingsView, {
      props: makeProps({ effectiveLLM: null, effectivePrefs: null }),
    })
    expect(pending.get("#project-settings-tab-panel").attributes("aria-busy")).toBe("true")
    expect(pending.get("#project-settings-tab-panel [role='status']").text()).toBe("加载中…")
    pending.unmount()

    const save = deferred()
    globalThis.api.projects.updateLlmSettings.mockReturnValue(save.promise)
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    void wrapper.find("#deep-import-tab-save").trigger("click")
    await Promise.resolve()
    expect(wrapper.get("#project-settings-tab-panel").attributes("aria-busy")).toBe("true")
    expect(wrapper.get("#deep-import-tab-save").attributes("aria-busy")).toBe("true")
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    expect(wrapper.get("#project-settings-tab-panel").attributes("aria-busy")).toBe("false")
    save.resolve()
    await flushPromises()
    expect(wrapper.get("#project-settings-tab-panel").attributes("aria-busy")).toBe("false")
  })
})

describe("深度导入", () => {
  it("未保存参数触发离开确认", async () => {
    const confirm = vi.fn(() => false)
    setBridgeOverrides({ confirm })
    let guard = null
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps(),
      global: {
        provide: {
          [ISLAND_LEAVE_GUARD]: (fn) => {
            guard = fn
          },
        },
      },
    })
    expect(guard()).toBe(true)
    await wrapper.find("#deep-import-phase0-target-input-chars").setValue("80000")
    expect(guard()).toBe(false)
    expect(confirm).toHaveBeenCalledWith(
      "项目设置有未保存修改，确定放弃并离开吗？",
    )
  })

  it("只提交 deep_import，不回传项目 provider/model/key", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.find("#deep-import-tab-save").trigger("click")

    await vi.waitFor(() => {
      expect(globalThis.toast).toHaveBeenCalledWith("深度导入参数已保存", "success")
    })
    const payload = globalThis.api.projects.updateLlmSettings.mock.calls[0][1]
    expect(payload.deep_import.phase0.target_input_chars).toBe(72000)
    expect(payload.provider_id).toBeUndefined()
    expect(payload.model).toBeUndefined()
    expect(payload.api_key).toBeUndefined()
  })

  it("越界参数不提交", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.find("#deep-import-phase0-target-input-chars").setValue("10")
    await wrapper.find("#deep-import-tab-save").trigger("click")
    expect(globalThis.api.projects.updateLlmSettings).not.toHaveBeenCalled()
    expect(globalThis.toast).toHaveBeenCalledWith(
      expect.stringContaining("必须是"),
      "warning",
    )
  })
})

describe("作者偏好", () => {
  it("以中文显示字体选项和项目来源值，同时保留原始 select value", async () => {
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps({
        effectivePrefs: makeEffectivePrefs({
          editor_font: { value: "system", source: "project" },
          default_focus_mode: { value: false, source: "project" },
        }),
      }),
    })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")

    const font = wrapper.find("#author-editor-font")
    expect(font.element.value).toBe("system")
    expect(font.findAll("option").map((option) => option.element.value)).toEqual([
      "system", "serif", "sans", "mono",
    ])
    expect(font.findAll("option").map((option) => option.text())).toEqual([
      "跟随系统", "衬线", "无衬线", "等宽",
    ])
    expect(wrapper.findAll(".author-prefs-tab .source-value").map((item) => item.text())).toContain("跟随系统")
    expect(wrapper.findAll(".author-prefs-tab .source-value").map((item) => item.text())).toContain("关闭")
  })

  it("保存项目偏好", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    await wrapper.find("#author-daily-goal").setValue("500")
    await wrapper.find("#author-prefs-tab-save").trigger("click")

    await vi.waitFor(() => {
      expect(globalThis.api.settings.updateProjectAuthorPrefs).toHaveBeenCalledWith(
        "p1",
        {
          daily_goal: 500,
          editor_font: "system",
          default_focus_mode: false,
        },
      )
    })
  })

  it("恢复单字段保留同表单其他草稿", async () => {
    globalThis.api.settings.getEffectiveAuthorPrefs.mockResolvedValue(
      makeEffectivePrefs({
        daily_goal: { value: 6000, source: "global" },
      }),
    )
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps({
        effectivePrefs: makeEffectivePrefs({
          daily_goal: { value: 3000, source: "project" },
        }),
      }),
    })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    await wrapper.find("#author-editor-font").setValue("serif")
    await wrapper.find('.field-reset[data-field="daily_goal"]').trigger("click")

    await vi.waitFor(() => {
      expect(wrapper.find("#author-daily-goal").element.value).toBe("6000")
    })
    expect(wrapper.find("#author-editor-font").element.value).toBe("serif")
    expect(globalThis.api.settings.getEffectiveLLMSettings).not.toHaveBeenCalled()
  })
})
