/**
 * settingsIslands 注册与 load 预取测试。
 * 模块加载即向 router mock（tests/setup.js）注册两个视图。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../vue/bridge/index.js"
import "../../vue/settingsIslands.js"

// 注册发生在模块加载时（一次性）；在 clearAllMocks 之前捕获视图对象引用
const views = registeredViews()

function registeredViews() {
  return globalThis.router.registerView.mock.calls.reduce(
    (map, [name, island]) => ({ ...map, [name]: island }),
    {},
  )
}

function setupWorkspace() {
  document.body.innerHTML = '<div id="workspace-content"></div>'
  return document.getElementById("workspace-content")
}

afterEach(() => {
  resetBridgeOverrides()
})

describe("settingsIslands 注册", () => {
  it("注册 settings / project-settings 两个视图", () => {
    const views = registeredViews()
    expect(views.settings).toBeTruthy()
    expect(views["project-settings"]).toBeTruthy()
  })
})

describe("settings island（全局设置）", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("onEnter 预取连接、余额和偏好并挂载账户设置", async () => {
    globalThis.api.settings.listLLMConnections.mockResolvedValue({
      active_provider_id: "deepseek",
      providers: [
        {
          provider_id: "deepseek",
          label: "DeepSeek",
          model: "deepseek-v4-flash",
          connected: true,
          active: true,
        },
      ],
    })
    globalThis.api.settings.listLLMBalances.mockResolvedValue({ items: [] })
    globalThis.api.settings.listGlobalAuthorPrefs.mockResolvedValue({ daily_goal: 800 })

    const island = views.settings
    await island.onEnter()
    const content = setupWorkspace()
    content.innerHTML = island.render()
    await island.onRendered()

    expect(content.querySelector(".global-settings-view")).toBeTruthy()
    expect(content.querySelector("#account-llm-save")).toBeTruthy()
    expect(content.querySelector(".account-provider-card")?.textContent)
      .toContain("DeepSeek")
    island.onLeave()
  })

  it("预取失败时降级为空数据并 toast，不阻断渲染", async () => {
    globalThis.api.settings.listLLMConnections.mockRejectedValue(new Error("网络错误"))
    globalThis.api.settings.listLLMBalances.mockRejectedValue(new Error("网络错误"))
    globalThis.api.settings.listGlobalAuthorPrefs.mockRejectedValue(new Error("网络错误"))

    const island = views.settings
    await island.onEnter()
    const content = setupWorkspace()
    content.innerHTML = island.render()
    await island.onRendered()

    expect(globalThis.toast).toHaveBeenCalledWith("加载全局设置失败", "error")
    expect(content.querySelector(".global-settings-view")).toBeTruthy()
    expect(content.textContent).toContain("模型连接")
    island.onLeave()
  })

  it("余额或作者偏好失败时仍保留模型连接卡片", async () => {
    globalThis.api.settings.listLLMConnections.mockResolvedValue({
      active_provider_id: "deepseek",
      providers: [{
        provider_id: "deepseek",
        label: "DeepSeek",
        model: "deepseek-v4-flash",
        connected: true,
        active: true,
      }],
    })
    globalThis.api.settings.listLLMBalances.mockRejectedValue(
      new Error("余额服务超时"),
    )
    globalThis.api.settings.listGlobalAuthorPrefs.mockRejectedValue(
      new Error("偏好暂时不可用"),
    )

    const island = views.settings
    await island.onEnter()
    const content = setupWorkspace()
    content.innerHTML = island.render()
    await island.onRendered()

    expect(content.querySelector(".account-provider-card")?.textContent)
      .toContain("DeepSeek")
    expect(content.querySelector("#account-llm-save")).toBeTruthy()
    expect(globalThis.toast).not.toHaveBeenCalledWith(
      "加载全局设置失败",
      "error",
    )
    island.onLeave()
  })
})

describe("project-settings island（项目设置）", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("无 currentProjectId 时渲染空态", async () => {
    setBridgeOverrides({ state: { currentProjectId: null, currentProject: null } })
    const island = views["project-settings"]
    await island.onEnter()
    const content = setupWorkspace()
    content.innerHTML = island.render()
    await island.onRendered()

    expect(content.querySelector(".settings-empty-state")).toBeTruthy()
    expect(content.textContent).toContain("请先进入项目")
    island.onLeave()
  })

  it("有项目时预取 effective 数据并挂载两个项目 Tab", async () => {
    setBridgeOverrides({
      state: { currentProjectId: "p1", currentProject: { title: "测试项目" } },
      tryMigrateLocalAuthorPreferences: vi.fn(),
    })
    globalThis.api.settings.getEffectiveLLMSettings.mockResolvedValue({
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
    })
    globalThis.api.settings.getEffectiveAuthorPrefs.mockResolvedValue({
      daily_goal: { value: null, source: "system" },
      editor_font: { value: "system", source: "system" },
      default_focus_mode: { value: false, source: "system" },
    })

    const island = views["project-settings"]
    await island.onEnter()
    const content = setupWorkspace()
    content.innerHTML = island.render()
    await island.onRendered()

    expect(content.querySelector(".project-settings-view")).toBeTruthy()
    expect(content.textContent).toContain("测试项目")
    expect(content.querySelectorAll(".settings-tab-nav .tab-btn")).toHaveLength(2)
    island.onLeave()
  })
})
