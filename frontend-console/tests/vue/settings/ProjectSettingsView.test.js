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

let appState

beforeEach(() => {
  vi.clearAllMocks()
  appState = { currentProjectId: "p1", currentView: "project-settings", currentSubView: null }
  setBridgeOverrides({ state: appState })
  projectSettingsSession.tab = "author"
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
    await wrapper.find("#project-settings-empty-goto-account").trigger("click")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("settings")
  })

  it("创作偏好在前，高级导入和模型连接保留次级入口", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    const tabs = wrapper.findAll(".settings-tab-nav .tab-btn")
    expect(tabs.map((item) => item.text())).toEqual(["创作偏好", "高级导入"])
    expect(wrapper.text()).toContain("AI 文本服务：DeepSeek · deepseek-v4-flash · 未连接")
    expect(wrapper.find("#llm-model").exists()).toBe(false)

    await wrapper.find("#project-settings-goto-global").trigger("click")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("settings")
  })

  it("作品级导入覆盖只显示作者摘要，不显示 raw 设置对象", async () => {
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps({
        effectiveLLM: makeEffectiveLLM({
          deep_import: {
            source: "project",
            value: { phase0: { target_input_chars: 80000 } },
          },
        }),
      }),
    })

    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")

    expect(wrapper.text()).toContain("当前作品有 1 项与默认不同")
    expect(wrapper.text()).not.toContain("target_input_chars")
    expect(wrapper.text()).not.toContain("80000")
    expect(wrapper.get("#deep-import-expert-fields").element.style.display).toBe("none")
  })

  it("Tab 选择在页面往返间保留", async () => {
    const first = mount(ProjectSettingsView, { props: makeProps() })
    await first.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    expect(first.find(".deep-import-tab").exists()).toBe(true)
    first.unmount()

    const second = mount(ProjectSettingsView, { props: makeProps() })
    expect(second.find(".deep-import-tab").exists()).toBe(true)
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
    expect(tabs[0].attributes("id")).toBe("project-settings-tab-author")
    expect(tabs[0].attributes("aria-controls")).toBe("project-settings-tab-panel")
    expect(tabs[0].attributes("tabindex")).toBe("0")
    expect(tabs[1].attributes("tabindex")).toBe("-1")
    expect(panel.attributes("aria-labelledby")).toBe("project-settings-tab-author")

    tabs[0].element.focus()
    await tabs[0].trigger("keydown", { key: "ArrowRight" })
    await vi.waitFor(() => expect(document.activeElement).toBe(tabs[1].element))
    expect(tabs[1].attributes("aria-selected")).toBe("true")
    expect(panel.attributes("aria-labelledby")).toBe("project-settings-tab-deep")
    expect(projectSettingsSession.tab).toBe("deep")

    await tabs[1].trigger("keydown", { key: "Home" })
    await vi.waitFor(() => expect(document.activeElement).toBe(tabs[0].element))
    expect(tabs[0].attributes("aria-selected")).toBe("true")
    wrapper.unmount()
  })

  it("面板在加载失败时可重试，保存期间公开真实忙碌状态", async () => {
    globalThis.api.settings.getEffectiveLLMSettings.mockResolvedValueOnce(makeEffectiveLLM())
    globalThis.api.settings.getEffectiveAuthorPrefs.mockResolvedValueOnce(makeEffectivePrefs())
    const pending = mount(ProjectSettingsView, {
      props: makeProps({
        effectiveLLM: null,
        effectivePrefs: null,
        loadError: "项目偏好暂时无法加载。已有设置没有改变。",
      }),
    })
    expect(pending.get("#project-settings-tab-panel").attributes("aria-busy")).toBe("false")
    expect(pending.get(".settings-load-error").attributes("role")).toBe("alert")
    await pending.get(".settings-load-error button").trigger("click")
    await flushPromises()
    expect(pending.find(".settings-load-error").exists()).toBe(false)
    expect(pending.find("#author-daily-goal").exists()).toBe(true)
    pending.unmount()

    const save = deferred()
    globalThis.api.projects.updateLlmSettings.mockReturnValue(save.promise)
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    void wrapper.find("#deep-import-tab-save").trigger("click")
    await Promise.resolve()
    expect(wrapper.get("#project-settings-tab-panel").attributes("aria-busy")).toBe("true")
    expect(wrapper.get("#deep-import-tab-save").attributes("aria-busy")).toBe("true")
    await wrapper.findAll(".settings-tab-nav .tab-btn")[0].trigger("click")
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
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    await wrapper.get('[aria-controls="deep-import-group-phase0"]').trigger("click")
    await wrapper.find("#deep-import-phase0-target-input-chars").setValue("80000")
    expect(guard()).toBe(false)
    expect(confirm).toHaveBeenCalledWith(
      "项目偏好有未保存修改，确定放弃并离开吗？",
    )
  })

  it("只提交 deep_import，不回传项目 provider/model/key", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    await wrapper.find("#deep-import-tab-save").trigger("click")

    await vi.waitFor(() => {
      expect(globalThis.toast).toHaveBeenCalledWith("深度导入参数已保存", "success")
    })
    const payload = globalThis.api.projects.updateLlmSettings.mock.calls[0][1]
    expect(payload.deep_import.phase0.target_input_chars).toBe(72000)
    expect(payload.provider_id).toBeUndefined()
    expect(payload.model).toBeUndefined()
    expect(payload.api_key).toBeUndefined()
    expect(globalThis.api.settings.getEffectiveAuthorPrefs).not.toHaveBeenCalled()
  })

  it("写入已成功时不把二次读取失败误报为保存失败", async () => {
    globalThis.api.settings.getEffectiveLLMSettings.mockRejectedValue(new Error("读取失败"))
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")

    await wrapper.find("#deep-import-tab-save").trigger("click")
    await flushPromises()

    expect(globalThis.api.projects.updateLlmSettings).toHaveBeenCalledOnce()
    expect(globalThis.toast).toHaveBeenCalledWith("深度导入参数已保存", "success")
    expect(globalThis.toast).toHaveBeenCalledWith(
      "已保存，但重新读取最新设置失败：读取失败",
      "warning",
    )
    expect(globalThis.toast).not.toHaveBeenCalledWith("读取失败", "error")
  })

  it("保存响应晚到且已离开项目偏好时不更新或提示", async () => {
    const save = deferred()
    globalThis.api.projects.updateLlmSettings.mockReturnValue(save.promise)
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")

    void wrapper.find("#deep-import-tab-save").trigger("click")
    await vi.waitFor(() => expect(globalThis.api.projects.updateLlmSettings).toHaveBeenCalled())
    appState.currentView = "today"
    save.resolve({})
    await flushPromises()

    expect(globalThis.toast).not.toHaveBeenCalled()
    expect(globalThis.api.settings.getEffectiveLLMSettings).not.toHaveBeenCalled()
    expect(globalThis.api.settings.getEffectiveAuthorPrefs).not.toHaveBeenCalled()
  })

  it("重置在当前页完成时保留成功反馈", async () => {
    setBridgeOverrides({ confirm: () => true })
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps({
        effectiveLLM: makeEffectiveLLM({
          deep_import: { value: {}, source: "project" },
        }),
      }),
    })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")

    await wrapper.find("#deep-import-tab-reset-all").trigger("click")
    await vi.waitFor(() => {
      expect(globalThis.toast).toHaveBeenCalledWith("深度导入参数已恢复默认", "success")
    })
    expect(globalThis.api.settings.resetLLMSettingsField)
      .toHaveBeenCalledWith("p1", "deep_import")
  })

  it("重置响应晚到且已离开项目偏好时不更新或提示", async () => {
    const reset = deferred()
    globalThis.api.settings.resetLLMSettingsField.mockReturnValue(reset.promise)
    setBridgeOverrides({ confirm: () => true })
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps({
        effectiveLLM: makeEffectiveLLM({
          deep_import: { value: {}, source: "project" },
        }),
      }),
    })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")

    void wrapper.find("#deep-import-tab-reset-all").trigger("click")
    await vi.waitFor(() => expect(globalThis.api.settings.resetLLMSettingsField).toHaveBeenCalled())
    appState.currentView = "today"
    reset.resolve({})
    await flushPromises()

    expect(globalThis.toast).not.toHaveBeenCalled()
    expect(globalThis.api.settings.getEffectiveLLMSettings).not.toHaveBeenCalled()
    expect(globalThis.api.settings.getEffectiveAuthorPrefs).not.toHaveBeenCalled()
  })

  it("越界参数不提交", async () => {
    const wrapper = mount(ProjectSettingsView, { attachTo: document.body, props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    await wrapper.get('[data-action="toggle-deep-import-expert"]').trigger("click")
    await wrapper.get('[aria-controls="deep-import-group-phase0"]').trigger("click")
    await wrapper.find("#deep-import-phase0-target-input-chars").setValue("10")
    await wrapper.get('[data-action="toggle-deep-import-expert"]').trigger("click")
    await wrapper.find("#deep-import-tab-save").trigger("click")
    expect(globalThis.api.projects.updateLlmSettings).not.toHaveBeenCalled()
    expect(globalThis.toast).toHaveBeenCalledWith(
      expect.stringContaining("必须是"),
      "warning",
    )
    await vi.waitFor(() => expect(document.activeElement?.id).toBe("deep-import-phase0-target-input-chars"))
    expect(wrapper.get("#deep-import-phase0-target-input-chars").attributes("aria-invalid")).toBe("true")
    expect(wrapper.get('[aria-controls="deep-import-group-phase0"]').attributes("aria-expanded")).toBe("true")
    expect(wrapper.get('[data-action="toggle-deep-import-expert"]').attributes("aria-expanded")).toBe("true")
  })

  it("深度导入问题组默认折叠，展开后提供字段说明", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    const expert = wrapper.get('[data-action="toggle-deep-import-expert"]')
    expect(expert.attributes("aria-expanded")).toBe("false")
    expect(expert.text()).toBe("查看专家参数")
    expect(wrapper.get("#deep-import-expert-fields").element.style.display).toBe("none")
    await expert.trigger("click")
    const group = wrapper.get('[aria-controls="deep-import-group-phase0"]')
    expect(group.attributes("aria-expanded")).toBe("false")
    expect(wrapper.get("#deep-import-phase0-target-input-chars").element.closest(".form-row").style.display).toBe("none")
    await group.trigger("click")
    expect(group.attributes("aria-expanded")).toBe("true")
    expect(wrapper.find("#deep-import-phase0-target-input-chars").attributes("aria-describedby")).toContain("-help")
    expect(wrapper.text()).toContain("调高会保留更多上下文或细节")
  })

  it("深度导入设置提供返回写作工作台", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "返回写作工作台").trigger("click")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("writing")
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
    await wrapper.find("#author-editor-font").setValue("serif")
    await wrapper.find('.field-reset[data-field="daily_goal"]').trigger("click")

    await vi.waitFor(() => {
      expect(wrapper.find("#author-daily-goal").element.value).toBe("6000")
    })
    expect(wrapper.find("#author-editor-font").element.value).toBe("serif")
    expect(globalThis.api.settings.getEffectiveLLMSettings).not.toHaveBeenCalled()
    expect(globalThis.toast).toHaveBeenCalledWith("日更目标已恢复到全局默认", "success")
  })
})
