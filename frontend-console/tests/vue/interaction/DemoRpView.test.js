import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import DemoRpView from "../../../vue/views/interaction/DemoRpView.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const source = {
  id: "source-1",
  title: "雨夜演示",
  status: "ready",
  anchors: [{ anchor_key: "anchor-1", chapter_title: "第一章" }],
}

function journey(overrides = {}) {
  return {
    id: "journey-1",
    title: "雨夜里的旅人",
    selection_epoch: 1,
    messages: [],
    ...overrides,
  }
}

let api

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  globalThis.accountAuthConfig = {
    terms_url: "/legal/terms",
    privacy_url: "/legal/privacy",
  }
  api = {
    auth: { anonymousRp: vi.fn(async () => ({ identity_type: "anonymous_rp" })) },
    interactions: {
      demoSource: vi.fn(async () => source),
      listDemoJourneys: vi.fn().mockRejectedValue({ status: 401 }),
      createDemoJourney: vi.fn(async () => ({
        journey: journey(),
        attempt: { id: "attempt-1", status: "running", visible_text: "" },
      })),
      streamDemoAttempt: vi.fn(async function* () {
        yield { event: "chunk", data: { text: "雨落在石阶上。", offset: 7 } }
        yield { event: "status", data: { status: "completed" } }
      }),
      getJourney: vi.fn(async () => journey({
        messages: [{ id: "story-1", role: "assistant", message_kind: "story", content: "雨落在石阶上。" }],
      })),
      sendMessage: vi.fn(),
      editUserMessage: vi.fn(),
      regenerate: vi.fn(),
      retryAttempt: vi.fn(async () => ({
        journey: journey({ selection_epoch: 2 }),
        attempt: { id: "attempt-2", status: "pending", visible_text: "" },
      })),
      listBranches: vi.fn(),
      selectBranch: vi.fn(),
      getOverview: vi.fn(),
      updateOverview: vi.fn(),
    },
  }
  setBridgeOverrides({ api })
})

afterEach(() => {
  resetBridgeOverrides()
  delete globalThis.accountAuthConfig
})

describe("匿名演示 RP", () => {
  it("优先恢复匿名会话中的最近旅程，不重复创建匿名身份", async () => {
    api.interactions.demoSource.mockReset().mockResolvedValue(source)
    api.interactions.listDemoJourneys.mockResolvedValue({ items: [{ id: "journey-1" }] })
    api.interactions.getJourney.mockResolvedValue(journey({
      setup_messages: [{ id: "setup-1", role: "user", message_kind: "setup", content: "我从雨夜进入雾港。" }],
      messages: [{ id: "story-1", role: "assistant", message_kind: "story", content: "已经抵达的故事。" }],
      active_attempt: { id: "attempt-1", status: "failed", error_message: "这次生成未完成，请重新生成" },
    }))

    const wrapper = mount(DemoRpView)
    await flushPromises()
    await flushPromises()

    expect(api.auth.anonymousRp).not.toHaveBeenCalled()
    expect(api.interactions.getJourney).toHaveBeenCalledWith("journey-1")
    expect(wrapper.text()).toContain("我从雨夜进入雾港。")
    expect(wrapper.text()).toContain("已经抵达的故事。")
    expect(wrapper.text()).toContain("这次生成未完成，请重新生成")
  })

  it("只在勾选协议后创建匿名会话", async () => {
    const wrapper = mount(DemoRpView)
    await flushPromises()

    expect(wrapper.get(".demo-rp-consent a[href='/legal/terms']").text()).toBe("用户协议")
    expect(wrapper.get(".demo-rp-consent a[href='/legal/privacy']").text()).toBe("隐私政策")
    await wrapper.get("#demo-deepseek-key").setValue("temporary-key")
    await wrapper.get("textarea[aria-label='演示旅程开场']").setValue("从这里开始。")
    expect(wrapper.get(".demo-rp-primary").element.disabled).toBe(true)
    expect(api.auth.anonymousRp).not.toHaveBeenCalled()

    await wrapper.get(".demo-rp-consent input").setValue(true)
    await wrapper.get(".demo-rp-primary").trigger("click")
    await flushPromises()

    expect(api.auth.anonymousRp).toHaveBeenCalledWith({
      accept_terms: true,
      accept_privacy: true,
    })
    expect(api.interactions.createDemoJourney).toHaveBeenCalledTimes(1)
  })

  it("用读者语言展示和编辑回顾，不暴露内部字段名", async () => {
    api.interactions.demoSource.mockReset().mockResolvedValue(source)
    api.interactions.listDemoJourneys.mockResolvedValue({ items: [{ id: "journey-1" }] })
    api.interactions.getJourney.mockResolvedValue(journey())
    api.interactions.getOverview.mockResolvedValue({
      overview_epoch: 1,
      sections: { world_and_start: "雨夜的旧城", current_situation: "正在寻找线索" },
    })
    const wrapper = mount(DemoRpView)
    await flushPromises()
    await flushPromises()

    await wrapper.findAll("button").find((button) => button.text() === "回顾").trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("世界与起点")
    expect(wrapper.text()).toContain("当前局面")
    expect(wrapper.text()).not.toContain("world_and_start")
    await wrapper.findAll("button").find((button) => button.text() === "手动纠正").trigger("click")
    expect(wrapper.text()).toContain("长期约定")
    expect(wrapper.find(".demo-rp-overview textarea").element.maxLength).toBe(4000)
  })

  it("将 direct stream 的终止错误保留为可恢复提示并刷新 attempt", async () => {
    api.interactions.streamDemoAttempt.mockReset().mockImplementation(async function* () {
      yield { event: "status", data: { status: "failed", error_kind: "rate_limit" } }
      yield { event: "done", data: { status: "failed", result_node_id: null } }
    })
    api.interactions.getJourney.mockResolvedValue(journey({
      active_attempt: { id: "attempt-1", status: "failed", error_kind: "rate_limit" },
    }))
    const wrapper = mount(DemoRpView)
    await flushPromises()
    await wrapper.get("#demo-deepseek-key").setValue("temporary-key")
    await wrapper.get("textarea[aria-label='演示旅程开场']").setValue("从这里开始。")
    await wrapper.get(".demo-rp-consent input").setValue(true)
    await wrapper.get(".demo-rp-primary").trigger("click")
    await flushPromises()
    await flushPromises()

    expect(api.interactions.getJourney).toHaveBeenCalledWith("journey-1")
    expect(wrapper.text()).toContain("请求过快，模型服务需要稍等片刻。")
    await wrapper.findAll("button").find((button) => button.text() === "换 Key 后重试").trigger("click")
    await flushPromises()

    expect(api.interactions.retryAttempt).toHaveBeenCalledWith(
      "journey-1",
      "attempt-1",
      expect.objectContaining({ expected_selection_epoch: 1 }),
    )
    expect(api.interactions.streamDemoAttempt).toHaveBeenLastCalledWith(
      "journey-1",
      "attempt-2",
      "temporary-key",
      expect.any(Object),
    )
  })

  it("只把临时 Key 留在当前页面内存，并只在 direct stream 中发送", async () => {
    const wrapper = mount(DemoRpView)
    await flushPromises()

    expect(api.auth.anonymousRp).not.toHaveBeenCalled()
    expect(api.interactions.demoSource).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).not.toContain("故事自主发展")
    expect(wrapper.text()).not.toContain("后台续写")
    expect(wrapper.text()).not.toContain("网页搜索")

    await wrapper.get("#demo-deepseek-key").setValue("temporary-key")
    await wrapper.get("textarea[aria-label='演示旅程开场']").setValue("我从雨夜进入这座城。")
    await wrapper.get(".demo-rp-consent input").setValue(true)
    await wrapper.get(".demo-rp-primary").trigger("click")
    await flushPromises()
    await flushPromises()

    expect(sessionStorage.getItem("ephemeralDeepSeekKey")).toBeNull()
    expect(localStorage.getItem("ephemeralDeepSeekKey")).toBeNull()
    expect(api.interactions.createDemoJourney).toHaveBeenCalledWith(expect.objectContaining({
      opening_text: "我从雨夜进入这座城。",
      see_sea_enabled: false,
      web_search_enabled: false,
      action_options_enabled: true,
    }))
    expect(api.interactions.streamDemoAttempt).toHaveBeenCalledWith(
      "journey-1",
      "attempt-1",
      "temporary-key",
      expect.any(Object),
    )
    expect(wrapper.text()).toContain("雨落在石阶上。")

    await wrapper.findAll("button").find((button) => button.text() === "清除临时 Key").trigger("click")
    expect(sessionStorage.getItem("ephemeralDeepSeekKey")).toBeNull()
  })
})
