/**
 * settingsIslands 注册与 load 预取测试。
 * 模块加载即向 router mock（tests/setup.js）注册三个视图。
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
  it("注册 settings / project-settings / llm 三个视图", () => {
    const views = registeredViews()
    expect(views.settings).toBeTruthy()
    expect(views["project-settings"]).toBeTruthy()
    expect(views.llm).toBeTruthy()
  })
})

describe("settings island（全局设置）", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("onEnter 预取四路数据，onRendered 挂载 GlobalSettingsView", async () => {
    globalThis.api.settings.listGlobalLLMDefaults.mockResolvedValue({
      base_url: "https://api.deepseek.com",
      model: "deepseek-v4-flash",
    })
    globalThis.api.settings.listGlobalAuthorPrefs.mockResolvedValue({ daily_goal: 800 })
    globalThis.api.settings.listProjectsUsingDefaults.mockResolvedValue({
      items: [{ project_id: "p1", title: "项目一" }],
      total: 1,
      truncated: false,
    })
    globalThis.api.projects.listLlmProviderTemplates.mockResolvedValue({ items: [] })

    const island = views.settings
    await island.onEnter()
    const content = setupWorkspace()
    content.innerHTML = island.render()
    await island.onRendered()

    expect(content.querySelector(".global-settings-view")).toBeTruthy()
    expect(content.querySelector("#global-llm-save")).toBeTruthy()
    expect(content.querySelector(".projects-using-list li")?.textContent).toContain("项目一")
    island.onLeave()
  })

  it("预取失败时降级为空数据并 toast，不阻断渲染", async () => {
    globalThis.api.settings.listGlobalLLMDefaults.mockRejectedValue(new Error("网络错误"))
    globalThis.api.settings.listGlobalAuthorPrefs.mockRejectedValue(new Error("网络错误"))
    globalThis.api.settings.listProjectsUsingDefaults.mockRejectedValue(new Error("网络错误"))
    globalThis.api.projects.listLlmProviderTemplates.mockRejectedValue(new Error("网络错误"))

    const island = views.settings
    await island.onEnter()
    const content = setupWorkspace()
    content.innerHTML = island.render()
    await island.onRendered()

    expect(globalThis.toast).toHaveBeenCalledWith("加载全局设置失败", "error")
    expect(content.querySelector(".global-settings-view")).toBeTruthy()
    expect(content.textContent).toContain("没有项目继承全局默认")
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

  it("有项目时预取 effective 数据并挂载三个 Tab", async () => {
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
    globalThis.api.projects.listLlmProviderTemplates.mockResolvedValue({ items: [] })

    const island = views["project-settings"]
    await island.onEnter()
    const content = setupWorkspace()
    content.innerHTML = island.render()
    await island.onRendered()

    expect(content.querySelector(".project-settings-view")).toBeTruthy()
    expect(content.textContent).toContain("测试项目")
    expect(content.querySelectorAll(".settings-tab-nav .tab-btn")).toHaveLength(3)
    island.onLeave()
  })
})

describe("#/llm 兼容别名（D15）", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("有项目时跳项目设置", async () => {
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    await views.llm.onEnter()
    expect(globalThis.router.navigate).toHaveBeenCalledWith("project-settings")
  })

  it("无项目时跳全局设置并提示", async () => {
    setBridgeOverrides({ state: { currentProjectId: null } })
    await views.llm.onEnter()
    expect(globalThis.router.navigate).toHaveBeenCalledWith("settings")
    expect(globalThis.toast).toHaveBeenCalledWith("请先选择项目", "warning")
  })
})
