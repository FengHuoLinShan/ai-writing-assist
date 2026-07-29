import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import GlobalSettingsView from "../../../vue/views/settings/GlobalSettingsView.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { ISLAND_LEAVE_GUARD } from "../../../vue/mountIsland.js"

function makeConnections(overrides = {}) {
  return {
    active_provider_id: "deepseek",
    providers: [
      {
        provider_id: "deepseek",
        label: "DeepSeek",
        model: "deepseek-v4-flash",
        connected: true,
        active: true,
        verified_at: "2026-07-28T00:00:00Z",
      },
      {
        provider_id: "kimi",
        label: "Kimi",
        model: "kimi-k3",
        connected: false,
        active: false,
        verified_at: null,
      },
    ],
    ...overrides,
  }
}

function makeProps(overrides = {}) {
  return {
    llmConnections: makeConnections(),
    llmBalances: {
      items: [
        {
          provider_id: "deepseek",
          status: "available",
          amount: "12.50",
          currency: "CNY",
        },
      ],
    },
    authorPrefs: {},
    ...overrides,
  }
}

function overrideProjectId(projectId) {
  setBridgeOverrides({
    state: { currentProjectId: projectId },
    onStateChange: () => () => {},
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("账户模型连接", () => {
  it("只呈现两种模板、Key 与只读余额", () => {
    overrideProjectId(null)
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })

    expect(wrapper.text()).toContain("账户设置")
    expect(wrapper.findAll(".account-provider-card")).toHaveLength(2)
    expect(wrapper.text()).toContain("deepseek-v4-flash")
    expect(wrapper.text()).toContain("kimi-k3")
    expect(wrapper.text()).toContain("余额 12.50 CNY")
    expect(wrapper.text()).toContain("余额可能有延迟")
    expect(wrapper.find("#account-llm-api-key").exists()).toBe(true)
    expect(wrapper.find("#llm-base-url").exists()).toBe(false)
    expect(wrapper.find("#llm-temperature").exists()).toBe(false)
    expect(wrapper.text()).not.toContain("owner: local")
  })

  it("有当前项目时可返回项目设置", async () => {
    overrideProjectId("p1")
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })
    await wrapper.find("#goto-recent-project-btn").trigger("click")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("project-settings")
  })

  it("未连接模板必须先填 Key", async () => {
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })
    await wrapper.findAll(".account-provider-card")[1].trigger("click")
    await wrapper.find("#account-llm-save").trigger("click")

    expect(globalThis.toast).toHaveBeenCalledWith("请先填写 API Key", "warning")
    expect(globalThis.api.settings.connectLLMProvider).not.toHaveBeenCalled()
  })

  it("填写 Key 后验证、保存并激活，Key 不进入本地存储", async () => {
    const next = makeConnections({
      active_provider_id: "kimi",
      providers: makeConnections().providers.map((provider) => ({
        ...provider,
        connected: true,
        active: provider.provider_id === "kimi",
      })),
    })
    globalThis.api.settings.connectLLMProvider.mockResolvedValueOnce(next)
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })
    await wrapper.findAll(".account-provider-card")[1].trigger("click")
    await wrapper.find("#account-llm-api-key").setValue("unit-test-kimi-key")
    await wrapper.find("#account-llm-save").trigger("click")

    await vi.waitFor(() => {
      expect(globalThis.api.settings.connectLLMProvider).toHaveBeenCalledWith(
        "kimi",
        "unit-test-kimi-key",
      )
    })
    expect(wrapper.find("#account-llm-api-key").element.value).toBe("")
    expect(JSON.stringify(localStorage)).not.toContain("unit-test-kimi-key")
    expect(globalThis.toast).toHaveBeenCalledWith(
      "已启用 Kimi，之后的新生成会使用此模型",
      "success",
    )
  })

  it("已验证模板留空 Key 时直接激活，不重复验证", async () => {
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })
    await wrapper.find("#account-llm-save").trigger("click")

    expect(globalThis.api.settings.activateLLMProvider).toHaveBeenCalledWith("deepseek")
    expect(globalThis.api.settings.connectLLMProvider).not.toHaveBeenCalled()
  })

  it("只接受严格旅程 UUID 作为连接后的返回位置", async () => {
    const navigate = vi.fn()
    setBridgeOverrides({
      router: {
        navigate,
        getCurrentQuery: () => new URLSearchParams({
          return_to: "interaction:11111111-1111-4111-8111-111111111111",
        }),
      },
    })
    const valid = mount(GlobalSettingsView, { props: makeProps() })
    await valid.find("#account-llm-save").trigger("click")
    expect(navigate).toHaveBeenCalledWith(
      "interaction",
      "11111111-1111-4111-8111-111111111111",
    )
    valid.unmount()

    navigate.mockClear()
    setBridgeOverrides({
      router: {
        navigate,
        getCurrentQuery: () => new URLSearchParams({
          return_to: "interaction:------------------------------------",
        }),
      },
    })
    const invalid = mount(GlobalSettingsView, { props: makeProps() })
    await invalid.find("#account-llm-save").trigger("click")
    expect(navigate).not.toHaveBeenCalled()
  })

  it("清除 Key 先确认并保留模板选择", async () => {
    const confirm = vi.fn(() => true)
    setBridgeOverrides({ confirm })
    globalThis.api.settings.clearLLMProvider.mockResolvedValueOnce({
      ...makeConnections(),
      providers: makeConnections().providers.map((provider) => (
        provider.provider_id === "deepseek"
          ? { ...provider, connected: false }
          : provider
      )),
    })
    const wrapper = mount(GlobalSettingsView, { props: makeProps() })
    await wrapper.find("#account-llm-clear").trigger("click")

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining(
      "作者创作与 RP 的新生成都会暂停",
    ))
    expect(globalThis.api.settings.clearLLMProvider).toHaveBeenCalledWith("deepseek")
    expect(wrapper.find(".account-provider-card.selected").text()).toContain("DeepSeek")
  })

  it("未保存 Key 会触发离开确认", async () => {
    const confirm = vi.fn(() => false)
    setBridgeOverrides({ confirm })
    let guard = null
    const wrapper = mount(GlobalSettingsView, {
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
    await wrapper.find("#account-llm-api-key").setValue("unsaved-key")
    expect(guard()).toBe(false)
    expect(confirm).toHaveBeenCalledWith(
      "账户设置有未保存修改，确定放弃并离开吗？",
    )
  })
})

describe("作者偏好", () => {
  it("合法值保存成功", async () => {
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
