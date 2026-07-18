/**
 * ProjectSettingsView 组件测试 — 对应原 projectSettingsView.test.js，
 * 并覆盖 Tab 切换、保存/重置流程。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { mount } from "@vue/test-utils"
import ProjectSettingsView from "../../../vue/views/settings/ProjectSettingsView.vue"
import { resetBridgeOverrides } from "../../../vue/bridge/index.js"
import { projectSettingsSession } from "../../../vue/views/settings/projectSettingsSession.js"

function makeEffectiveLLM(overrides = {}) {
  return {
    provider_id: { value: "deepseek", source: "system" },
    label: { value: "DeepSeek", source: "system" },
    base_url: { value: "https://api.deepseek.com", source: "system" },
    model: { value: "deepseek-v4-flash", source: "system" },
    timeout: { value: 180, source: "system" },
    max_tokens: { value: 12000, source: "system" },
    temperature: { value: 0.3, source: "system" },
    top_p: { value: null, source: "unset" },
    extra: { value: {}, source: "system" },
    api_key_configured: { value: false, source: "unset" },
    api_key_configured_providers: { value: [], source: "unset" },
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
    templates: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  projectSettingsSession.tab = "main"
  globalThis.api.settings.getEffectiveLLMSettings.mockImplementation(async () => makeEffectiveLLM())
  globalThis.api.settings.getEffectiveAuthorPrefs.mockImplementation(async () => makeEffectivePrefs())
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("空态与导航", () => {
  it("无 projectId 渲染空态，按钮跳全局设置", async () => {
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps({ projectId: null, effectiveLLM: null, effectivePrefs: null }),
    })
    expect(wrapper.find(".settings-empty-state").exists()).toBe(true)
    expect(wrapper.text()).toContain("请先进入项目")
    await wrapper.find("#project-settings-goto-global").trigger("click")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("settings")
  })

  it("effective 数据缺失时显示加载中", () => {
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps({ effectiveLLM: null, effectivePrefs: null }),
    })
    expect(wrapper.text()).toContain("加载中…")
  })
})

describe("Tab 渲染与切换（原 vanilla Tab 契约）", () => {
  it("默认主配置 Tab，三个 Tab 可切换", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    const tabs = wrapper.findAll(".settings-tab-nav .tab-btn")
    expect(tabs.map((tab) => tab.text())).toEqual(["主配置", "深度导入", "作者偏好"])
    expect(wrapper.find(".llm-main-tab").exists()).toBe(true)
    expect(wrapper.find("#llm-max-tokens").element.value).toBe("12000")

    await tabs[1].trigger("click")
    expect(wrapper.find(".deep-import-tab").exists()).toBe(true)
    expect(wrapper.text()).toContain("深度导入不继承“默认输出上限”")
    expect(wrapper.text()).toContain("Phase 0 Plan")

    await tabs[2].trigger("click")
    expect(wrapper.find(".author-prefs-tab").exists()).toBe(true)
    expect(wrapper.find("#author-daily-goal").exists()).toBe(true)

    await tabs[0].trigger("click")
    expect(wrapper.find(".llm-main-tab").exists()).toBe(true)
  })

  it("Tab 选择跨页面往返保留（vanilla _tab 单例语义，P3 回归）", async () => {
    const first = mount(ProjectSettingsView, { props: makeProps() })
    await first.findAll(".settings-tab-nav .tab-btn")[2].trigger("click")
    expect(first.find(".author-prefs-tab").exists()).toBe(true)

    // 模拟路由往返：island 卸载后重新挂载
    first.unmount()
    const second = mount(ProjectSettingsView, { props: makeProps() })
    expect(second.find(".author-prefs-tab").exists()).toBe(true)
    expect(second.findAll(".settings-tab-nav .tab-btn")[2].classes()).toContain("active")
  })
})

describe("Key 状态跨 Tab 一致性（P2 回归）", () => {
  const DEEPSEEK_TEMPLATE = {
    id: "deepseek",
    name: "DeepSeek",
    base_url: "https://api.deepseek.com",
    default_model: "deepseek-v4-flash",
    models: ["deepseek-v4-flash"],
    default_parameters: { timeout: 180, max_tokens: 12000, temperature: 0.3 },
  }
  const OTHER_TEMPLATE = {
    id: "other",
    name: "Other",
    base_url: "https://other.example.com/v1",
    default_model: "other-model",
    models: ["other-model"],
    default_parameters: { timeout: 60 },
  }

  it("切换供应商 → 切 Tab → 返回，Key 状态仍按新供应商显示", async () => {
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps({
        effectiveLLM: makeEffectiveLLM({
          api_key_configured: { value: true, source: "project" },
        }),
        templates: [DEEPSEEK_TEMPLATE, OTHER_TEMPLATE],
      }),
    })
    expect(wrapper.find("#llm-key-status").text()).toBe("已保存")

    await wrapper.find("#llm-provider").setValue("other")
    expect(wrapper.find("#llm-key-status").text()).toBe("此模板未保存")

    await wrapper.findAll(".settings-tab-nav .tab-btn")[2].trigger("click")
    await wrapper.findAll(".settings-tab-nav .tab-btn")[0].trigger("click")
    expect(wrapper.find("#llm-key-status").text()).toBe("此模板未保存")
  })
})

describe("主配置保存", () => {
  it("保存调用 updateLlmSettings 并刷新 effective；Key 未配置时给警告", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.find("#llm-tab-save").trigger("click")
    await vi.waitFor(() => {
      expect(globalThis.toast).toHaveBeenCalledWith("Key 未配置，已保存其他字段", "warning")
    })

    const call = globalThis.api.projects.updateLlmSettings.mock.calls[0]
    expect(call[0]).toBe("p1")
    expect(call[1]).toMatchObject({ provider_id: "deepseek", api_key: "", clear_api_key: false })
    expect(globalThis.api.settings.getEffectiveLLMSettings).toHaveBeenCalledWith("p1")
    expect(globalThis.api.settings.getEffectiveAuthorPrefs).toHaveBeenCalledWith("p1")
  })

  it("数值越界时仅警告", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.find("#llm-max-tokens").setValue("0")
    await wrapper.find("#llm-tab-save").trigger("click")
    expect(globalThis.api.projects.updateLlmSettings).not.toHaveBeenCalled()
    expect(globalThis.toast).toHaveBeenCalledWith(expect.stringContaining("非法"), "warning")
  })

  it("恢复所有字段需确认，确认后调用重置载荷", async () => {
    const { setBridgeOverrides } = await import("../../../vue/bridge/index.js")
    setBridgeOverrides({ confirm: () => true })
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.find("#llm-tab-reset-all").trigger("click")
    await vi.waitFor(() => {
      expect(globalThis.toast).toHaveBeenCalledWith("已恢复所有 LLM 字段到全局默认", "success")
    })
    const payload = globalThis.api.projects.updateLlmSettings.mock.calls[0][1]
    expect(payload).toMatchObject({ provider_id: null, clear_api_key: true, clear_all_api_keys: true })
  })

  it("取消确认时不调接口", async () => {
    const { setBridgeOverrides } = await import("../../../vue/bridge/index.js")
    setBridgeOverrides({ confirm: () => false })
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.find("#llm-tab-reset-all").trigger("click")
    expect(globalThis.api.projects.updateLlmSettings).not.toHaveBeenCalled()
  })
})

describe("深度导入", () => {
  it("越界校验给出字段级警告", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    await wrapper.find("#deep-import-phase0-target-input-chars").setValue("10")
    await wrapper.find("#deep-import-tab-save").trigger("click")

    expect(globalThis.api.projects.updateLlmSettings).not.toHaveBeenCalled()
    expect(globalThis.toast).toHaveBeenCalledWith(expect.stringContaining("必须是"), "warning")
  })

  it("合法值保存 deep_import 载荷（保留项目级其他覆盖）", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    await wrapper.find("#deep-import-tab-save").trigger("click")
    await vi.waitFor(() => {
      expect(globalThis.toast).toHaveBeenCalledWith("深度导入参数已保存", "success")
    })
    const payload = globalThis.api.projects.updateLlmSettings.mock.calls[0][1]
    expect(payload.deep_import.phase0.target_input_chars).toBe(72000)
    // 项目无其他字段覆盖时回传 null（继承语义）
    expect(payload.provider_id).toBeNull()
  })
})

describe("作者偏好", () => {
  it("保存项目偏好并刷新", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[2].trigger("click")
    await wrapper.find("#author-daily-goal").setValue("500")
    await wrapper.find("#author-prefs-tab-save").trigger("click")
    await vi.waitFor(() => {
      expect(globalThis.toast).toHaveBeenCalledWith("作者偏好已保存", "success")
    })
    expect(globalThis.api.settings.updateProjectAuthorPrefs).toHaveBeenCalledWith("p1", {
      daily_goal: 500,
      editor_font: "system",
      default_focus_mode: false,
    })
  })

  it("项目覆盖字段显示恢复到全局默认按钮并触发重置", async () => {
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps({
        effectivePrefs: makeEffectivePrefs({
          daily_goal: { value: 3000, source: "project" },
        }),
      }),
    })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[2].trigger("click")
    const resetButton = wrapper.find('.field-reset[data-field="daily_goal"]')
    expect(resetButton.exists()).toBe(true)
    await resetButton.trigger("click")
    await vi.waitFor(() => {
      expect(globalThis.api.settings.resetProjectAuthorPrefsField).toHaveBeenCalledWith("p1", "daily_goal")
    })
  })
})
