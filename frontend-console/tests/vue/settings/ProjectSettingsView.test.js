import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import ProjectSettingsView from "../../../vue/views/settings/ProjectSettingsView.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { ISLAND_LEAVE_GUARD } from "../../../vue/mountIsland.js"
import { projectSettingsSession } from "../../../vue/views/settings/projectSettingsSession.js"
import { DEEP_IMPORT_GROUPS } from "../../../vue/views/settings/logic/deepImport.js"

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
  globalThis.api.assistant = {
    capabilities: vi.fn(async () => ({
      enabled: true,
      collaboration: [],
      rehearsal: { available: true, reason: null },
      model: { available: true, reason: null },
    })),
    operationTraceReport: vi.fn(async () => ({
      schema_version: "1",
      period: "30d",
      timezone: "UTC",
      as_of: "2026-10-16T00:00:00+00:00",
      window_start: "2026-09-17",
      window_end: "2026-10-16",
      collection_enabled_now: true,
      events: [],
      operation_candidates: [],
      sequences: [],
      parameter_profiles: [],
      lifecycle: [],
      metrics: [],
      coverage: {
        status: "no_records",
        completeness_provable: false,
        capture_enabled_now: true,
        first_record_date: null,
        last_record_date: null,
        days_with_records: 0,
        missing_metric_event_count: 0,
        missing_lifecycle_event_count: 0,
        incomplete_legacy_sequence_count: 0,
        parameter_profile_gap_by_operation: {},
        legacy_event_aggregates_preserved: true,
        note: "只展示实际记录样本。",
      },
    })),
  }
  globalThis.api.interactions = {
    listJourneys: vi.fn(async () => ({ items: [], total: 0 })),
  }
  globalThis.api.localAgent = {
    devices: vi.fn(async () => ({ items: [{ id: "mac-1", name: "作者的 Mac", paired: true, online: true }] })),
    executor: vi.fn(async () => ({ kind: "gateway", device_id: null })),
    pending: vi.fn(async () => ({ items: [] })),
    pair: vi.fn(async () => ({ code: "synthetic-code" })),
    select: vi.fn(async () => ({ kind: "claude", device_id: "mac-1" })),
    revoke: vi.fn(async () => ({ revoked: true })),
  }
  globalThis.api.projects.getObjectDossierSettings = vi.fn(async () => ({ version: 0, allow_story_override: false }))
  globalThis.api.projects.setObjectDossierSettings = vi.fn(async (_projectId, payload) => ({
    version: payload.expected_version + 1,
    allow_story_override: payload.allow_story_override,
  }))
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("结构与导航", () => {
  it("本机 CLI 选择保存到当前作品并说明每轮权限，且只用于生图", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await flushPromises()
    await wrapper.findAll(".settings-tab-nav .tab-btn")[2].trigger("click")
    expect(wrapper.text()).toContain("本机 CLI 生图")
    expect(wrapper.text()).toContain("只用于生成世界对象图片和地图册页面")
    expect(wrapper.text()).toContain("项目助手、RP、前瞻等文字功能一律使用账户模型连接")
    expect(wrapper.text()).toContain("专用工作目录不是沙箱")
    const kindSelect = wrapper.find("#local-agent-kind")
    expect(kindSelect.findAll("option")[0].text()).toBe("不使用本机 CLI")
    await kindSelect.setValue("claude")
    await wrapper.find("#local-agent-device").setValue("mac-1")
    const save = wrapper.findAll("button").find(button => button.text() === "保存生图执行器")
    await save.trigger("click")
    expect(globalThis.api.localAgent.select).toHaveBeenCalledWith("p1", "claude", "mac-1")
  })
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
    await flushPromises()
    const tabs = wrapper.findAll(".settings-tab-nav .tab-btn")
    expect(tabs.map((item) => item.text())).toEqual(["创作偏好", "高级导入", "AI 能力", "操作留痕"])
    expect(wrapper.text()).toContain("AI 文本服务：DeepSeek · deepseek-v4-flash · 未连接")
    expect(wrapper.find("#llm-model").exists()).toBe(false)

    await wrapper.find("#project-settings-goto-global").trigger("click")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("settings")
  })

  it("操作留痕在作品设置加载失败时仍可从作者设置页打开", async () => {
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps({
        effectiveLLM: null,
        effectivePrefs: null,
        loadError: "设置读取失败",
      }),
    })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[3].trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("真实操作留痕")
    expect(wrapper.text()).toContain("当前范围没有留痕记录")
    expect(wrapper.text()).not.toContain("当前作品的设置暂时无法加载")
    expect(globalThis.api.assistant.operationTraceReport).toHaveBeenCalledWith(
      "p1",
      "30d",
      expect.any(Object),
    )
  })

  it("模型提示使用账户当前连接 metadata，不误读旧的有效设置模型", async () => {
    globalThis.api.settings.listLLMConnections.mockResolvedValueOnce({
      active_provider_id: "deepseek",
      providers: [{
        provider_id: "deepseek",
        label: "DeepSeek",
        model: "deepseek-flash",
        connected: true,
        active: true,
      }],
    })
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps({
        effectiveLLM: makeEffectiveLLM({
          model: { value: "deepseek-v4-flash", source: "global" },
        }),
      }),
    })

    await flushPromises()

    expect(wrapper.text()).toContain("AI 文本服务：DeepSeek · deepseek-flash")
    expect(wrapper.text()).not.toContain("deepseek-v4-flash")
  })

  it("账户连接 metadata 读取失败时不显示旧模型值", async () => {
    globalThis.api.settings.listLLMConnections.mockRejectedValueOnce(new Error("连接读取失败"))
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })

    await flushPromises()

    expect(wrapper.text()).toContain("AI 文本服务：账户连接暂时无法读取")
    expect(wrapper.text()).not.toContain("deepseek-v4-flash")
  })

  it("作品级导入覆盖只显示作者摘要，不显示 raw 设置对象", async () => {
    const fullDefaults = Object.fromEntries(DEEP_IMPORT_GROUPS.map((group) => [
      group.id,
      Object.fromEntries(group.fields.map((field) => [field.key, field.type === "nullableBool" ? null : field.value])),
    ]))
    const defaultsWrapper = mount(ProjectSettingsView, {
      props: makeProps({
        effectiveLLM: makeEffectiveLLM({
          deep_import: { source: "project", value: fullDefaults },
        }),
      }),
    })
    await defaultsWrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")
    expect(defaultsWrapper.text()).toContain("当前作品使用已保存设置")
    expect(defaultsWrapper.text()).not.toContain("项与默认不同")
    defaultsWrapper.unmount()

    const configured = structuredClone(fullDefaults)
    configured.phase0.target_input_chars = 80000
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps({
        effectiveLLM: makeEffectiveLLM({
          deep_import: { source: "project", value: configured },
        }),
      }),
    })

    await wrapper.findAll(".settings-tab-nav .tab-btn")[1].trigger("click")

    expect(wrapper.text()).toContain("当前作品有 1 项与默认不同")
    expect(wrapper.text()).not.toContain("target_input_chars")
    expect(wrapper.text()).not.toContain("80000")
    expect(wrapper.get('[data-action="toggle-deep-import-expert"]').attributes("aria-expanded")).toBe("false")
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

describe("世界对象有效期设置", () => {
  it("默认作者区间优先，并在保存成功后才显示剧情覆盖已开启", async () => {
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await flushPromises()

    const toggle = wrapper.get("#project-object-dossier-override")
    expect(toggle.element.checked).toBe(false)
    expect(wrapper.text()).toContain("已保存：作者区间优先")
    await toggle.setValue(true)
    await flushPromises()

    expect(globalThis.api.projects.setObjectDossierSettings).toHaveBeenCalledWith("p1", {
      expected_version: 0,
      allow_story_override: true,
    })
    expect(wrapper.get("#project-object-dossier-override").element.checked).toBe(true)
    expect(wrapper.text()).toContain("已保存：剧情覆盖已开启")
    wrapper.unmount()
  })

  it("409 保留选择并重读版本，重试后以新的 CAS 版本保存", async () => {
    const conflict = Object.assign(new Error("设置版本已变化"), { status: 409 })
    globalThis.api.projects.getObjectDossierSettings
      .mockResolvedValueOnce({ version: 0, allow_story_override: false })
      .mockResolvedValueOnce({ version: 2, allow_story_override: false })
    globalThis.api.projects.setObjectDossierSettings
      .mockRejectedValueOnce(conflict)
      .mockResolvedValueOnce({ version: 3, allow_story_override: true })
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await flushPromises()

    await wrapper.get("#project-object-dossier-override").setValue(true)
    await flushPromises()
    expect(wrapper.get("#project-object-dossier-override").element.checked).toBe(true)
    expect(wrapper.text()).toContain("你的选择仍保留")
    await wrapper.get(".settings-save-state.is-error button").trigger("click")
    await flushPromises()

    expect(globalThis.api.projects.setObjectDossierSettings).toHaveBeenNthCalledWith(2, "p1", {
      expected_version: 2,
      allow_story_override: true,
    })
    expect(wrapper.text()).toContain("已保存：剧情覆盖已开启")
    wrapper.unmount()
  })

  it("项目切换后忽略旧项目的迟到读取", async () => {
    const oldRead = deferred()
    globalThis.api.projects.getObjectDossierSettings.mockImplementation((projectId) => (
      projectId === "p1"
        ? oldRead.promise
        : Promise.resolve({ version: 7, allow_story_override: false })
    ))
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await Promise.resolve()
    appState.currentProjectId = "p2"
    await wrapper.setProps({ projectId: "p2" })
    await flushPromises()
    oldRead.resolve({ version: 99, allow_story_override: true })
    await flushPromises()

    expect(wrapper.get("#project-object-dossier-override").element.checked).toBe(false)
    expect(wrapper.text()).toContain("已保存：作者区间优先")
    expect(wrapper.text()).not.toContain("已保存：剧情覆盖已开启")
    wrapper.unmount()
  })
})

describe("AI 能力", () => {
  function makeCapabilities(overrides = {}) {
    return {
      enabled: true,
      collaboration: [
        { id: "deep_review", label: "深度审稿", experimental: true, available: true, reason: null },
        { id: "blind_reader", label: "盲读者检查", experimental: true, available: false, reason: "这项专项协作尚未开启" },
      ],
      rehearsal: { available: true, reason: null },
      model: { available: true, reason: null },
      ...overrides,
    }
  }

  it("列出蓝图、排演与多角色状态，不暴露内部 id", async () => {
    globalThis.api.assistant.capabilities.mockImplementation(
      async () => makeCapabilities(),
    )
    globalThis.api.interactions.listJourneys.mockImplementation(
      async () => ({
        items: [{
          id: "j1",
          title: "雾中廷根",
          source: { source_title: "诡秘之主" },
          ensemble_available: true,
          latest_activity_at: "2026-09-20T10:00:00Z",
        }],
        total: 1,
      }),
    )
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[2].trigger("click")
    await flushPromises()

    const rows = wrapper.findAll(".ai-capability-row")
    const labels = rows.map((row) => row.find(".ai-capability-label").text()).join("|")
    expect(labels).toContain("深度审稿")
    expect(labels).toContain("盲读者检查")
    expect(labels).toContain("多人物排演")
    expect(wrapper.text()).toContain("这项专项协作尚未开启")
    expect(wrapper.text()).toContain("旅程「雾中廷根」")
    expect(wrapper.text()).not.toContain("deep_review")
    expect(wrapper.text()).not.toContain("blind_reader")
    expect(wrapper.text()).not.toContain("reason")
  })

  it("无绑源旅程时多角色演绎给引导文案而非误导原因", async () => {
    globalThis.api.assistant.capabilities.mockImplementation(
      async () => makeCapabilities(),
    )
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[2].trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("需在互动故事中创建绑定作品资料的旅程后使用")
    expect(wrapper.text()).not.toContain("多角色演绎尚未开启")
  })

  it("模型未连接时提示并提供去连接入口", async () => {
    globalThis.api.assistant.capabilities.mockImplementation(
      async () => makeCapabilities({
        model: { available: false, reason: "请先连接并验证当前模型，讨论记录仍可查看。" },
      }),
    )
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[2].trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("请先连接并验证当前模型")
    await wrapper.findAll("button").find((button) => button.text() === "去连接模型").trigger("click")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("settings")
  })

  it("能力读取失败时保留可重试的错误卡，不影响其他页签", async () => {
    globalThis.api.assistant.capabilities.mockRejectedValue(new Error("读取失败"))
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[2].trigger("click")
    await flushPromises()

    expect(wrapper.find(".ai-capabilities-tab .settings-load-error").attributes("role")).toBe("alert")
    expect(wrapper.find("#author-daily-goal").exists()).toBe(false)

    globalThis.api.assistant.capabilities.mockImplementation(async () => makeCapabilities())
    await wrapper.find(".ai-capabilities-tab .settings-load-error button").trigger("click")
    await flushPromises()
    expect(wrapper.find(".ai-capabilities-tab .settings-load-error").exists()).toBe(false)
    expect(wrapper.text()).toContain("深度审稿")

    await wrapper.findAll(".settings-tab-nav .tab-btn")[0].trigger("click")
    expect(wrapper.find("#author-daily-goal").exists()).toBe(true)
  })
})

describe("AI 用量", () => {
  function makeUsage(overrides = {}) {
    return {
      window_days: 30,
      tasks_scanned: 2,
      tasks_with_envelope: 2,
      unreadable_envelopes: 0,
      scan_truncated: false,
      totals: {
        requests: 4,
        requests_unknown: 0,
        input_tokens: 130,
        output_tokens: 70,
        charge_unconfirmed: false,
      },
      capabilities: [
        {
          capability: "writing.generate",
          label: "AI 写作",
          tasks: 1,
          requests: 2,
          requests_unknown: 0,
          input_tokens: 100,
          output_tokens: 50,
          charge_unconfirmed: false,
        },
        {
          capability: "writing.semantic_review",
          label: "正文独立审查",
          tasks: 1,
          requests: 2,
          requests_unknown: 0,
          input_tokens: 30,
          output_tokens: 20,
          charge_unconfirmed: false,
        },
      ],
      attribution: {
        buckets: [
          { key: "adopted", label: "已写进作品的成果", tasks: 1, requests: 2, requests_unknown: 0, input_tokens: 100, output_tokens: 50, charge_unconfirmed: false },
          { key: "pending", label: "进行中或等你处理的候选", tasks: 0, requests: 0, requests_unknown: 0, input_tokens: 0, output_tokens: 0, charge_unconfirmed: false },
          { key: "not_adopted", label: "未采用或返修", tasks: 1, requests: 2, requests_unknown: 0, input_tokens: 30, output_tokens: 20, charge_unconfirmed: false },
          { key: "failed", label: "失败与恢复", tasks: 0, requests: 0, requests_unknown: 0, input_tokens: 0, output_tokens: 0, charge_unconfirmed: false },
          { key: "other", label: "资料整理等辅助消耗", tasks: 0, requests: 0, requests_unknown: 0, input_tokens: 0, output_tokens: 0, charge_unconfirmed: false },
        ],
      },
      ...overrides,
    }
  }

  async function openUsageTab(usage) {
    globalThis.api.projects.aiUsage = vi.fn(async () => usage)
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await wrapper.findAll(".settings-tab-nav .tab-btn")[2].trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "统计当前作品用量").trigger("click")
    await flushPromises()
    return wrapper
  }

  it("全知回执只显示已知数字，不出现未知文案", async () => {
    const wrapper = await openUsageTab(makeUsage())

    expect(globalThis.api.projects.aiUsage).toHaveBeenCalledWith("p1", 30)
    expect(wrapper.text()).toContain("共 2 次 AI 运行，已确认 4 次模型请求的用量")
    expect(wrapper.text()).toContain("130")
    expect(wrapper.text()).not.toContain("部分用量未知")
    expect(wrapper.text()).not.toContain("计费状态未确认")
    expect(wrapper.text()).not.toContain("计费未确认")
  })

  it("部分未知与计费未确认如实展示，已知数字不变", async () => {
    const usage = makeUsage({
      totals: {
        requests: 4,
        requests_unknown: 1,
        input_tokens: 130,
        output_tokens: 70,
        charge_unconfirmed: true,
      },
      capabilities: [
        {
          capability: "writing.generate",
          label: "AI 写作",
          tasks: 1,
          requests: 2,
          requests_unknown: 0,
          input_tokens: 100,
          output_tokens: 50,
          charge_unconfirmed: false,
        },
        {
          capability: "writing.semantic_review",
          label: "正文独立审查",
          tasks: 1,
          requests: 2,
          requests_unknown: 1,
          input_tokens: 30,
          output_tokens: 20,
          charge_unconfirmed: true,
        },
      ],
    })
    const wrapper = await openUsageTab(usage)

    expect(wrapper.text()).toContain("共 2 次 AI 运行，已确认 4 次模型请求的用量")
    expect(wrapper.text()).toContain("部分用量未知：另有 1 次模型请求已发出但用量无法确认")
    expect(wrapper.text()).toContain("部分请求的计费状态未确认")
    expect(wrapper.text()).toContain("计费未确认")
    // 未知请求单列展示，不折算进已知数字
    const header = wrapper.findAll(".data-table th").map((th) => th.text())
    expect(header).toContain("用量未知请求")
  })

  it("按作品成果归因展示消耗去向，作者语言不暴露内部状态", async () => {
    const wrapper = await openUsageTab(makeUsage())

    const attribution = wrapper.get(".usage-attribution")
    expect(attribution.text()).toContain("这些用量花在了哪里")
    expect(attribution.text()).toContain("已写进作品的成果")
    expect(attribution.text()).toContain("进行中或等你处理的候选")
    expect(attribution.text()).toContain("未采用或返修")
    expect(attribution.text()).toContain("失败与恢复")
    expect(attribution.text()).toContain("资料整理等辅助消耗")
    const headers = attribution.findAll("th").map((th) => th.text())
    expect(headers).toEqual(["消耗去向", "AI 运行", "已确认用量请求", "输入词元", "输出词元"])
    expect(wrapper.text()).not.toContain("adopted")
    expect(wrapper.text()).not.toContain("not_adopted")
    expect(wrapper.text()).not.toContain("writing.generate")
  })

  it("归因桶沿用未知语义：未知请求单列并标注计费未确认", async () => {
    const usage = makeUsage({
      totals: {
        requests: 4,
        requests_unknown: 2,
        input_tokens: 130,
        output_tokens: 70,
        charge_unconfirmed: true,
      },
      attribution: {
        buckets: [
          { key: "adopted", label: "已写进作品的成果", tasks: 1, requests: 2, requests_unknown: 0, input_tokens: 100, output_tokens: 50, charge_unconfirmed: false },
          { key: "pending", label: "进行中或等你处理的候选", tasks: 0, requests: 0, requests_unknown: 0, input_tokens: 0, output_tokens: 0, charge_unconfirmed: false },
          { key: "not_adopted", label: "未采用或返修", tasks: 0, requests: 0, requests_unknown: 0, input_tokens: 0, output_tokens: 0, charge_unconfirmed: false },
          { key: "failed", label: "失败与恢复", tasks: 0, requests: 0, requests_unknown: 0, input_tokens: 0, output_tokens: 0, charge_unconfirmed: false },
          { key: "other", label: "资料整理等辅助消耗", tasks: 1, requests: 2, requests_unknown: 2, input_tokens: 30, output_tokens: 20, charge_unconfirmed: true, usage_complete: false },
        ],
      },
    })
    const wrapper = await openUsageTab(usage)

    const attributionText = wrapper.get(".usage-attribution").text()
    expect(attributionText).toContain("其中 2 次请求用量未知")
    expect(attributionText).toContain("（计费未确认）")
    expect(attributionText).toContain("用量统计不完整，不能视为零消耗")
    // 已知数字不被未知折算污染
    expect(wrapper.text()).toContain("部分用量未知：另有 2 次模型请求已发出但用量无法确认")
  })
  it.each([0, 2])("未确认用量不会显示为总请求数（未知次数 %i）", async (unknown) => {
    const wrapper = await openUsageTab(makeUsage({ totals: { requests: 0, requests_unknown: unknown, input_tokens: 0, output_tokens: 0, charge_unconfirmed: false, usage_complete: false } }))
    expect(wrapper.text()).toContain("已确认 0 次模型请求的用量")
    expect(wrapper.text()).toContain("用量统计不完整")
    expect(wrapper.text()).toContain("不能视为零消耗")
    expect(wrapper.text()).not.toContain("共 0 次模型请求")
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
    expect(wrapper.get('[data-action="toggle-deep-import-expert"]').attributes("aria-expanded")).toBe("false")
    await expert.trigger("click")
    const group = wrapper.get('[aria-controls="deep-import-group-phase0"]')
    expect(group.attributes("aria-expanded")).toBe("false")
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

describe("导出图片包", () => {
  function stubExportManifest(objects) {
    globalThis.api.world.imageExportManifest.mockImplementation(
      async () => ({ novel_id: "p1", objects }),
    )
  }

  it("作者页签在「导出作品」之后渲染图片包区块并区分两种导出", async () => {
    stubExportManifest([])
    const wrapper = mount(ProjectSettingsView, { props: makeProps() })
    await flushPromises()
    const html = wrapper.html()
    expect(html).toContain("导出作品")
    expect(html.indexOf('data-testid="image-export-panel"')).toBeGreaterThan(html.indexOf("导出作品"))
    const panel = wrapper.find('[data-testid="image-export-panel"]')
    expect(panel.text()).toContain("导出图片包")
    expect(panel.text()).toContain("由浏览器在本机打包")
    expect(panel.text()).toContain("「导出作品」导出的是文字，由服务端生成")
  })

  it("已生成的分包下载列表保留离开保护", async () => {
    const confirm = vi.fn(() => false)
    setBridgeOverrides({ confirm })
    let guard
    const wrapper = mount(ProjectSettingsView, {
      props: makeProps(),
      global: {
        stubs: { ImageExportPanel: { template: "<div />", data: () => ({ busy: false, hasDownloadPackages: true }) } },
        provide: { [ISLAND_LEAVE_GUARD]: fn => { guard = fn } },
      },
    })
    await flushPromises()
    expect(guard()).toBe(false)
    expect(confirm).toHaveBeenCalledWith("图片包下载列表将在离开后清除，请确认已经保存全部文件。确定离开吗？")
    await wrapper.get('[data-tab="deep"]').trigger("click")
    expect(wrapper.get('[data-tab="author"]').attributes("aria-selected")).toBe("true")
    expect(confirm).toHaveBeenLastCalledWith("切换页签会清除图片包下载列表，请确认已经保存全部文件。确定继续吗？")
    await wrapper.get('[data-tab="author"]').trigger("keydown", { key: "ArrowRight" })
    expect(wrapper.get('[data-tab="author"]').attributes("aria-selected")).toBe("true")
    confirm.mockReturnValue(true)
    expect(guard()).toBe(true)
    await wrapper.get('[data-tab="author"]').trigger("keydown", { key: "ArrowRight" })
    expect(wrapper.get('[data-tab="deep"]').attributes("aria-selected")).toBe("true")
    wrapper.unmount()
  })

  it("图片包生成中触发离开确认并说明不会留下半成品文件", async () => {
    const confirm = vi.fn(() => false)
    setBridgeOverrides({ confirm })
    stubExportManifest([{
      novel_id: "p1",
      category: "map_page",
      bucket: "maps",
      key: "map-atlas/p1/pages/44444444-4444-4444-8444-000000000001/image.png",
      content_type: "image/png",
      sha256: null,
      byte_size: null,
      page_id: "44444444-4444-4444-8444-000000000001",
      title: "封面",
    }])
    globalThis.api.world.fetchMapAtlasImage.mockImplementation(
      () => new Promise(() => {}),
    )
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
    await flushPromises()
    expect(guard()).toBe(true)
    await wrapper.get('[data-testid="image-export-start"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-testid="image-export-progress"]').exists()).toBe(true))
    expect(guard()).toBe(false)
    expect(confirm).toHaveBeenCalledWith(
      "图片包还在生成中，离开会中止导出且不会留下文件。确定离开吗？",
    )
  })
})
