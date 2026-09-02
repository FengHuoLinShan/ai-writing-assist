import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import InteractionView from "../../../vue/views/interaction/InteractionView.vue"
import {
  resetBridgeOverrides,
  setBridgeOverrides,
} from "../../../vue/bridge/index.js"
import { ISLAND_LEAVE_GUARD } from "../../../vue/mountIsland.js"

function message(id, role, content, overrides = {}) {
  return {
    id,
    parent_node_id: null,
    role,
    message_kind: "story",
    content,
    completion_state: "complete",
    branch_hint: content.slice(0, 20),
    story_ended: false,
    action_suggestions: [],
    created_at: "2026-07-28T00:00:00Z",
    ...overrides,
  }
}

function journey(overrides = {}) {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    title: "廷根雨夜",
    title_source: "model",
    opening_text: "我来到廷根。",
    status: "active",
    see_sea_enabled: false,
    action_options_enabled: true,
    selection_epoch: 3,
    overview_epoch: 0,
    selected_leaf_node_id: "a2",
    setup_messages: [
      message("setup-1", "user", "我来到廷根。", { message_kind: "setup" }),
    ],
    messages: [
      message("u1", "user", "我推开门。"),
      message("a1", "assistant", "旧的一段故事。", {
        action_suggestions: [{ label: "旧选项", text: "选择旧发展" }],
      }),
      message("u2", "user", "我继续向前。"),
      message("a2", "assistant", "最新的一段故事。", {
        action_suggestions: [{ label: "追上去", text: "我立刻追上去。" }],
      }),
    ],
    has_older_messages: false,
    active_attempt: null,
    ...overrides,
  }
}

function connected() {
  return {
    active_provider_id: "deepseek",
    providers: [{
      provider_id: "deepseek",
      label: "DeepSeek",
      model: "deepseek-v4-flash",
      connected: true,
      active: true,
    }],
  }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function makeApi(overrides = {}) {
  const baseJourney = journey()
  return {
    interactions: {
      getJourney: vi.fn(async () => baseJourney),
      getPathIndex: vi.fn(async () => ({
        selection_epoch: 3,
        items: [
          { id: "a1", ordinal: 1, total: 2, excerpt: "旧的一段故事。" },
          { id: "a2", ordinal: 2, total: 2, excerpt: "最新的一段故事。" },
        ],
      })),
      getMessages: vi.fn(),
      getOverview: vi.fn(async () => ({
        sections: {
          world_and_start: "廷根的雨夜。",
          player_character: "一名记者。",
          current_situation: "正在追查马车。",
          important_people_and_factions: "",
          key_turning_points: "",
          open_threads: "马车主人是谁。",
          must_remember: "",
        },
        source: "automatic",
        overview_epoch: 0,
        anchor_node_id: "a2",
        base_revision_id: "overview-revision-1",
        base_selected_leaf_node_id: "a2",
        base_selected_path_hash: "a".repeat(64),
        status: "ready",
        is_refreshing: false,
      })),
      updateOverview: vi.fn(async (_id, payload) => ({
        sections: payload.sections,
        source: "manual",
        overview_epoch: 1,
        anchor_node_id: "a2",
        base_revision_id: "overview-revision-2",
        base_selected_leaf_node_id: "a2",
        base_selected_path_hash: "b".repeat(64),
        status: "ready",
        is_refreshing: false,
      })),
      retryOverview: vi.fn(),
      listGenerationRecords: vi.fn(async () => ({ items: [] })),
      sendMessage: vi.fn(),
      editUserMessage: vi.fn(),
      regenerate: vi.fn(),
      listBranches: vi.fn(async () => ({ variants: [] })),
      selectBranch: vi.fn(),
      getTree: vi.fn(async () => ({ branch_points: [] })),
      updateModes: vi.fn(),
      heartbeat: vi.fn(async () => ({ accepted: true })),
      leaveJourney: vi.fn(async () => ({ accepted: false })),
      acknowledgeSeeSeaNotice: vi.fn(async () => ({
        see_sea_notice_acknowledged: true,
      })),
      stopAttempt: vi.fn(),
      streamAttempt: vi.fn(async function* () {}),
      retryAttempt: vi.fn(),
      continueAttempt: vi.fn(),
      keepAttempt: vi.fn(),
      continueFromNode: vi.fn(),
      updateTitle: vi.fn(),
      archiveJourney: vi.fn(),
      exportJourney: vi.fn(),
      ...overrides,
    },
  }
}

let api
let router
let toast
let confirm

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  api = makeApi()
  router = {
    navigate: vi.fn(),
    getCurrentQuery: vi.fn(() => new URLSearchParams()),
  }
  toast = vi.fn()
  confirm = vi.fn(() => true)
  Element.prototype.scrollIntoView = vi.fn()
  setBridgeOverrides({
    api,
    router,
    toast,
    confirm,
    prompt: vi.fn(),
  })
})

afterEach(() => {
  window.getSelection()?.removeAllRanges()
  resetBridgeOverrides()
  vi.restoreAllMocks()
})

describe("RP 故事页", () => {
  it("旅程加载失败时只显示恢复入口，不启动旅程副作用", () => {
    const wrapper = mount(InteractionView, {
      props: { initialJourney: null, loadError: "当前旅程无法访问" },
    })

    expect(wrapper.get(".rp-load-failure").text()).toContain("当前旅程无法访问")
    expect(api.interactions.getPathIndex).not.toHaveBeenCalled()
    expect(api.interactions.heartbeat).not.toHaveBeenCalled()
  })

  it("分开折叠开场设定，只给最新故事保留选项和重抽入口", async () => {
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
        initialPathIndex: {
          selection_epoch: 3,
          items: [
            { id: "a1", ordinal: 1, total: 2, excerpt: "旧的一段故事。" },
            { id: "a2", ordinal: 2, total: 2, excerpt: "最新的一段故事。" },
          ],
        },
      },
    })

    expect(wrapper.get(".rp-setup-history").text()).toContain("我来到廷根")
    expect(wrapper.text()).not.toContain("旧选项")
    expect(wrapper.text()).toContain("追上去")
    expect(wrapper.findAll(".rp-message__actions button")
      .filter((button) => button.text() === "重新生成")).toHaveLength(1)

    await wrapper.get(".rp-action-options button").trigger("click")
    expect(wrapper.get("textarea[aria-label='继续旅程']").element.value)
      .toBe("我立刻追上去。")
    expect(api.interactions.sendMessage).not.toHaveBeenCalled()

    const composer = wrapper.get("textarea[aria-label='继续旅程']")
    await composer.setValue("我先观察四周。")
    composer.element.setSelectionRange(
      composer.element.value.length,
      composer.element.value.length,
    )
    await wrapper.get(".rp-action-options button").trigger("click")
    expect(composer.element.value).toBe("我先观察四周。\n我立刻追上去。")
    expect(api.interactions.sendMessage).not.toHaveBeenCalled()
  })

  it("导出成功给出明确反馈", async () => {
    api.interactions.exportJourney.mockResolvedValue({
      content: "# 廷根雨夜",
      media_type: "text/markdown",
      filename: "廷根雨夜.md",
    })
    const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:journey")
    const revokeUrl = vi.spyOn(URL, "revokeObjectURL")
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
    const wrapper = mount(InteractionView, {
      props: { initialJourney: journey(), llmConnections: connected() },
    })

    await wrapper.findAll("button").find((button) => button.text() === "导出完整记录").trigger("click")
    await flushPromises()

    expect(api.interactions.exportJourney).toHaveBeenCalledWith(journey().id, {
      format: "md",
      story_only: false,
      include_overview: true,
    })
    expect(createUrl).toHaveBeenCalledWith(expect.any(Blob))
    expect(revokeUrl).toHaveBeenCalledWith("blob:journey")
    expect(toast).toHaveBeenCalledWith("完整记录已导出", "success")
    wrapper.unmount()
  })

  it.each(["成功", "失败"])("离页后的导出%s响应不再下载或提示", async (outcome) => {
    const request = deferred()
    api = makeApi({ exportJourney: vi.fn(() => request.promise) })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:late")
    const wrapper = mount(InteractionView, {
      props: { initialJourney: journey(), llmConnections: connected() },
    })

    await wrapper.findAll("button")
      .find((button) => button.text() === "导出完整记录")
      .trigger("click")
    await Promise.resolve()
    wrapper.unmount()

    if (outcome === "成功") {
      request.resolve({
        content: "# 迟到的导出",
        media_type: "text/markdown",
        filename: "迟到.md",
      })
    } else {
      request.reject(new Error("late private failure"))
    }
    await flushPromises()

    expect(createUrl).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it("安全显示模型 Markdown，并让完整行动建议只填入输入框", async () => {
    const longAction = "我先放慢脚步，完整观察门缝里的影子，再决定是否推门进入。"
    const markdown = "## 门后的钟声\n\n**克莱恩**听见了第二次敲击。"
    const initialJourney = journey({
      messages: [
        message("u2", "user", "我继续向前。"),
        message("a2", "assistant", markdown, {
          action_suggestions: [{
            label: "谨慎观察",
            text: longAction,
          }],
        }),
      ],
    })
    const writeText = vi.fn(async () => undefined)
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney,
        llmConnections: connected(),
      },
    })
    const assistantMessage = wrapper.get("[data-rp-message-id='a2']")

    expect(assistantMessage.get("h2").text()).toBe("门后的钟声")
    expect(assistantMessage.get("strong").text()).toBe("克莱恩")
    expect(assistantMessage.get(".rp-action-card__label").text()).toBe("谨慎观察")
    expect(assistantMessage.get(".rp-action-card__text").text()).toBe(longAction)

    const actions = assistantMessage.findAll(".rp-message__actions button")
    const copyIndex = actions.findIndex((button) => button.text() === "复制")
    expect(copyIndex).toBeGreaterThanOrEqual(0)
    expect(actions[copyIndex + 1].text()).toBe("重新生成")
    expect(actions[copyIndex].classes()).toContain("rp-message-action-button")
    expect(actions[copyIndex + 1].classes()).toContain("rp-message-action-button")

    await actions[copyIndex].trigger("click")
    expect(writeText).toHaveBeenCalledWith(markdown)

    await assistantMessage.get(".rp-action-card").trigger("click")
    expect(wrapper.get("textarea[aria-label='继续旅程']").element.value).toBe(longAction)
    expect(writeText).toHaveBeenCalledTimes(1)
    expect(api.interactions.sendMessage).not.toHaveBeenCalled()
    expect(api.interactions.regenerate).not.toHaveBeenCalled()
  })

  it("只在真实分岔时显示位置并用完整行动文本，切换时保留草稿并淡提示", async () => {
    api = makeApi({
      listBranches: vi.fn(async () => ({
        variants: [
          {
            node_id: "a2-other",
            selected: false,
            ordinal: 1,
            total: 2,
            excerpt: "我留在钟楼继续调查。",
          },
          {
            node_id: "a2",
            selected: true,
            ordinal: 2,
            total: 2,
            excerpt: "最新的一段故事。",
          },
        ],
      })),
      selectBranch: vi.fn(async () => journey({
        selection_epoch: 4,
        selected_leaf_node_id: "a2-other",
      })),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
        initialPathIndex: {
          selection_epoch: 3,
          items: [
            { id: "a1", ordinal: 1, total: 2, excerpt: "旧的一段故事。" },
            { id: "a2", ordinal: 2, total: 2, excerpt: "最新的一段故事。" },
          ],
        },
      },
    })
    await flushPromises()

    expect(wrapper.get(".rp-action-card__text").text())
      .toBe("我立刻追上去。")
    const branchButton = wrapper.findAll(".rp-message__actions button")
      .find((button) => button.text() === "其他分支 2/2")
    expect(branchButton).toBeTruthy()
    await branchButton.trigger("click")

    const branchPopover = wrapper.get(".rp-branch-popover")
    expect(branchPopover.attributes("role")).toBe("group")
    expect(branchPopover.attributes("aria-label")).toBe("选择故事分支")
    expect(branchPopover.findAll("button")
      .find((button) => button.text().includes("最新的一段故事"))
      .attributes("aria-pressed")).toBe("true")
    expect(branchPopover.findAll("button")
      .find((button) => button.text().includes("我留在钟楼"))
      .attributes("aria-pressed")).toBe("false")

    await wrapper.get("textarea[aria-label='继续旅程']").setValue("我先检查怀表。")
    const otherBranch = wrapper.findAll(".rp-branch-popover button")
      .find((button) => button.text().includes("我留在钟楼"))
    await otherBranch.trigger("click")
    await flushPromises()

    expect(confirm).not.toHaveBeenCalled()
    expect(api.interactions.selectBranch).toHaveBeenCalled()
    expect(wrapper.get("textarea[aria-label='继续旅程']").element.value)
      .toBe("我先检查怀表。")
    expect(wrapper.text()).toContain("已切换发展；草稿仍保留")
  })

  it("右侧定位可加载尚未挂载的旧节点窗口，并校验选择 epoch", async () => {
    api.interactions.getMessages.mockResolvedValueOnce({
      items: [
        message("u0", "user", "更早的行动。"),
        message("a0", "assistant", "最早的一段故事。"),
      ],
      has_older: false,
      has_newer: true,
      selection_epoch: 3,
    })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
        initialPathIndex: {
          selection_epoch: 3,
          items: [
            { id: "a0", ordinal: 1, total: 3, excerpt: "最早的一段故事。" },
            { id: "a1", ordinal: 2, total: 3, excerpt: "旧的一段故事。" },
            { id: "a2", ordinal: 3, total: 3, excerpt: "最新的一段故事。" },
          ],
        },
      },
    })

    const locator = wrapper.get(".rp-locator-rail input")
    await locator.setValue("1")
    await locator.trigger("change")
    await flushPromises()

    expect(api.interactions.getMessages).toHaveBeenCalledWith(
      journey().id,
      { around_node_id: "a0", limit: 20 },
    )
    expect(wrapper.text()).toContain("最早的一段故事")
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
  })

  it("切换分支后丢弃旧选择 epoch 迟到的更早分页", async () => {
    const olderPage = deferred()
    let selectedEpoch = 3
    api = makeApi({
      getMessages: vi.fn(async (_journeyId, params) => {
        if (params.before_node_id) return olderPage.promise
        return {
          items: [message("a9", "assistant", "另一条当前发展。")],
          has_older: false,
          has_newer: false,
          selection_epoch: selectedEpoch,
        }
      }),
      getPathIndex: vi.fn(async () => ({
        selection_epoch: selectedEpoch,
        items: selectedEpoch === 3
          ? [{ id: "a2", ordinal: 1, total: 1, excerpt: "原发展" }]
          : [{ id: "a9", ordinal: 1, total: 1, excerpt: "另一发展" }],
      })),
      listBranches: vi.fn(async (_journeyId, nodeId) => ({
        variants: nodeId === "a2"
          ? [
              {
                node_id: "a2",
                selected: true,
                ordinal: 1,
                total: 2,
                excerpt: "原发展",
              },
              {
                node_id: "a9",
                selected: false,
                ordinal: 2,
                total: 2,
                excerpt: "另一发展",
              },
            ]
          : [],
      })),
      selectBranch: vi.fn(async () => {
        selectedEpoch = 4
        return journey({
          selection_epoch: 4,
          selected_leaf_node_id: "a9",
          has_older_messages: false,
          messages: [
            message("u9", "user", "我选择另一条路。"),
            message("a9", "assistant", "另一条当前发展。"),
          ],
        })
      }),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey({ has_older_messages: true }),
        llmConnections: connected(),
      },
    })
    await flushPromises()

    void wrapper.get(".rp-load-older").trigger("click")
    await Promise.resolve()
    await wrapper.findAll(".rp-message__actions button")
      .find((button) => button.text().startsWith("其他分支"))
      .trigger("click")
    await flushPromises()
    await wrapper.findAll(".rp-branch-popover button")
      .find((button) => button.text().includes("另一发展"))
      .trigger("click")
    await flushPromises()

    olderPage.resolve({
      items: [message("stale-a0", "assistant", "不应混入的旧分支正文。")],
      has_older: false,
      has_newer: true,
      selection_epoch: 3,
    })
    await flushPromises()

    expect(wrapper.text()).toContain("另一条当前发展")
    expect(wrapper.text()).not.toContain("不应混入的旧分支正文")
  })

  it("阅读旧窗口时不抢回最新，只统计新增的模型故事段", async () => {
    const streamDone = deferred()
    const running = journey({
      active_attempt: {
        id: "attempt-reading-old-window",
        journey_id: journey().id,
        response_to_node_id: "u2",
        status: "running",
        visible_text: "",
        visible_offset: 0,
      },
    })
    api.interactions.streamAttempt.mockImplementation(async function* () {
      await streamDone.promise
    })
    api.interactions.getMessages.mockResolvedValue({
      items: [
        message("u0", "user", "很久以前的行动。"),
        message("a0", "assistant", "很久以前的故事。", {
          story_ended: true,
          action_suggestions: [{ label: "旧选项", text: "选择旧选项" }],
        }),
      ],
      has_older: false,
      has_newer: true,
      selection_epoch: 3,
    })
    api.interactions.getJourney.mockResolvedValue(journey({
      selected_leaf_node_id: "a3",
      active_attempt: null,
      messages: [
        ...journey().messages,
        message("u3", "user", "另一标签页的新行动。"),
        message("a3", "assistant", "模型新生成的一段。"),
      ],
    }))
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: running,
        llmConnections: connected(),
        initialPathIndex: {
          selection_epoch: 3,
          items: [
            { id: "a0", ordinal: 1, total: 3, excerpt: "很久以前" },
            { id: "a1", ordinal: 2, total: 3, excerpt: "旧的一段" },
            { id: "a2", ordinal: 3, total: 3, excerpt: "最新一段" },
          ],
        },
      },
    })

    await wrapper.get(".rp-locator-ticks button").trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("很久以前的故事")
    expect(wrapper.text()).not.toContain("选择旧选项")
    expect(wrapper.text()).not.toContain("故事在这里告一段落")
    expect(wrapper.findAll(".rp-message__actions button")
      .filter((button) => button.text() === "重新生成")).toHaveLength(0)

    streamDone.resolve()
    await flushPromises()

    expect(wrapper.text()).toContain("很久以前的故事")
    expect(wrapper.text()).not.toContain("模型新生成的一段")
    expect(wrapper.get(".rp-new-content").text()).toContain("有 1 段新内容")
  })

  it("刷新旅程的迟到响应不能覆盖期间刚选中的分支", async () => {
    const staleRefresh = deferred()
    let selectedEpoch = 3
    const running = journey({
      active_attempt: {
        id: "attempt-stale-refresh",
        journey_id: journey().id,
        response_to_node_id: "u2",
        status: "running",
        visible_text: "",
        visible_offset: 0,
      },
    })
    api = makeApi({
      getJourney: vi.fn(() => staleRefresh.promise),
      streamAttempt: vi.fn(async function* () {
        yield { event: "status", data: { status: "completed" } }
      }),
      listBranches: vi.fn(async (_journeyId, nodeId) => ({
        variants: nodeId === "a2"
          ? [
              {
                node_id: "a2",
                selected: true,
                ordinal: 1,
                total: 2,
                excerpt: "原发展",
              },
              {
                node_id: "a9",
                selected: false,
                ordinal: 2,
                total: 2,
                excerpt: "刚选中的新分支",
              },
            ]
          : [],
      })),
      getPathIndex: vi.fn(async () => ({
        selection_epoch: selectedEpoch,
        items: selectedEpoch === 3
          ? [{ id: "a2", ordinal: 1, total: 1, excerpt: "原发展" }]
          : [{ id: "a9", ordinal: 1, total: 1, excerpt: "新分支" }],
      })),
      selectBranch: vi.fn(async () => {
        selectedEpoch = 4
        return journey({
          selection_epoch: 4,
          selected_leaf_node_id: "a9",
          active_attempt: null,
          messages: [
            message("u9", "user", "我改走另一条路。"),
            message("a9", "assistant", "这是刚选中的新分支。"),
          ],
        })
      }),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: running,
        llmConnections: connected(),
      },
    })
    await flushPromises()
    expect(api.interactions.getJourney).toHaveBeenCalledTimes(1)

    await wrapper.findAll(".rp-message__actions button")
      .find((button) => button.text().startsWith("其他分支"))
      .trigger("click")
    await flushPromises()
    await wrapper.findAll(".rp-branch-popover button")
      .find((button) => button.text().includes("刚选中的新分支"))
      .trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("这是刚选中的新分支")

    staleRefresh.resolve(journey({
      selection_epoch: 3,
      selected_leaf_node_id: "a2",
      active_attempt: null,
    }))
    await flushPromises()

    expect(wrapper.text()).toContain("这是刚选中的新分支")
    expect(wrapper.text()).not.toContain("最新的一段故事")
  })

  it("回到最新的迟到响应不能覆盖期间刚选中的分支", async () => {
    const staleLatest = deferred()
    let selectedEpoch = 3
    api = makeApi({
      getMessages: vi.fn(async () => ({
        items: [
          message("u0", "user", "更早的行动。"),
          message("a0", "assistant", "正在阅读的旧窗口。"),
        ],
        has_older: false,
        has_newer: true,
        selection_epoch: 3,
      })),
      getJourney: vi.fn(() => staleLatest.promise),
      getTree: vi.fn(async () => ({
        branch_points: [{
          parent_node_id: "u1",
          label: "门口的选择",
          variants: [{
            node_id: "a9",
            selected: false,
            ordinal: 2,
            total: 2,
            excerpt: "转入新分支",
          }],
        }],
      })),
      selectBranch: vi.fn(async () => {
        selectedEpoch = 4
        return journey({
          selection_epoch: 4,
          selected_leaf_node_id: "a9",
          messages: [
            message("u9", "user", "我转入另一条路。"),
            message("a9", "assistant", "这是刚选中的新分支。"),
          ],
        })
      }),
      getPathIndex: vi.fn(async () => ({
        selection_epoch: selectedEpoch,
        items: selectedEpoch === 3
          ? [
              { id: "a0", ordinal: 1, total: 3, excerpt: "旧窗口" },
              { id: "a1", ordinal: 2, total: 3, excerpt: "中间" },
              { id: "a2", ordinal: 3, total: 3, excerpt: "最新" },
            ]
          : [{ id: "a9", ordinal: 1, total: 1, excerpt: "新分支" }],
      })),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
        initialPathIndex: {
          selection_epoch: 3,
          items: [
            { id: "a0", ordinal: 1, total: 3, excerpt: "旧窗口" },
            { id: "a1", ordinal: 2, total: 3, excerpt: "中间" },
            { id: "a2", ordinal: 3, total: 3, excerpt: "最新" },
          ],
        },
      },
    })
    await wrapper.get(".rp-locator-ticks button").trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("正在阅读的旧窗口")

    void wrapper.get(".rp-new-content").trigger("click")
    await Promise.resolve()
    expect(api.interactions.getJourney).toHaveBeenCalledTimes(1)

    await wrapper.findAll(".rp-more-menu > div > button")
      .find((button) => button.text() === "查看所有分支")
      .trigger("click")
    await flushPromises()
    await wrapper.get(".rp-tree-branch button").trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("这是刚选中的新分支")

    staleLatest.resolve(journey({
      selection_epoch: 3,
      selected_leaf_node_id: "a2",
      messages: [
        ...journey().messages,
        message("a3", "assistant", "不应覆盖新分支的迟到正文。"),
      ],
    }))
    await flushPromises()

    expect(wrapper.text()).toContain("这是刚选中的新分支")
    expect(wrapper.text()).not.toContain("不应覆盖新分支的迟到正文")
  })

  it("元数据操作保留历史窗口，切换分支后再明确回到新窗口", async () => {
    let selectedEpoch = 3
    api = makeApi({
      getMessages: vi.fn(async () => ({
        items: [
          message("u0", "user", "更早的行动。"),
          message("a0", "assistant", "仍在阅读的旧窗口。"),
        ],
        has_older: false,
        has_newer: true,
        selection_epoch: 3,
      })),
      updateModes: vi.fn(async () => ({
        journey: journey({ action_options_enabled: false }),
        attempt: null,
      })),
      getTree: vi.fn(async () => ({
        branch_points: [{
          parent_node_id: "u1",
          label: "门口的选择",
          variants: [{
            node_id: "a9",
            selected: false,
            ordinal: 2,
            total: 2,
            excerpt: "转入新分支",
          }],
        }],
      })),
      selectBranch: vi.fn(async () => {
        selectedEpoch = 4
        return journey({
          selection_epoch: 4,
          selected_leaf_node_id: "a9",
          action_options_enabled: false,
          messages: [
            message("u9", "user", "我转入新分支。"),
            message("a9", "assistant", "新分支的最新窗口。"),
          ],
        })
      }),
      getPathIndex: vi.fn(async () => ({
        selection_epoch: selectedEpoch,
        items: selectedEpoch === 3
          ? [
              { id: "a0", ordinal: 1, total: 3, excerpt: "旧窗口" },
              { id: "a1", ordinal: 2, total: 3, excerpt: "中间" },
              { id: "a2", ordinal: 3, total: 3, excerpt: "最新" },
            ]
          : [{ id: "a9", ordinal: 1, total: 1, excerpt: "新分支" }],
      })),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
        initialPathIndex: {
          selection_epoch: 3,
          items: [
            { id: "a0", ordinal: 1, total: 3, excerpt: "旧窗口" },
            { id: "a1", ordinal: 2, total: 3, excerpt: "中间" },
            { id: "a2", ordinal: 3, total: 3, excerpt: "最新" },
          ],
        },
      },
    })
    await wrapper.get(".rp-locator-ticks button").trigger("click")
    await flushPromises()

    await wrapper.findAll(".rp-composer-tools button")
      .find((button) => button.text() === "行动选项")
      .trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("仍在阅读的旧窗口")
    expect(wrapper.text()).not.toContain("最新的一段故事")
    expect(wrapper.find(".rp-new-content").exists()).toBe(true)

    await wrapper.findAll(".rp-more-menu > div > button")
      .find((button) => button.text() === "查看所有分支")
      .trigger("click")
    await flushPromises()
    await wrapper.get(".rp-tree-branch button").trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("新分支的最新窗口")
    expect(wrapper.text()).not.toContain("仍在阅读的旧窗口")
    expect(wrapper.find(".rp-new-content").exists()).toBe(false)
    expect(wrapper.findAll(".rp-message__actions button")
      .filter((button) => button.text() === "重新生成")).toHaveLength(1)
  })

  it("等待续写时保留草稿，但发送按钮和快捷键都不会提交", async () => {
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey({
          active_attempt: {
            id: "attempt-awaiting-continue",
            journey_id: journey().id,
            response_to_node_id: "a2",
            status: "awaiting_continue",
            visible_text: "这段尚未写完。",
            visible_offset: 8,
          },
        }),
        llmConnections: connected(),
      },
    })
    const input = wrapper.get("textarea[aria-label='继续旅程']")
    await input.setValue("先保存为草稿，不立即发送。")

    expect(wrapper.get(".rp-send-button").element.disabled).toBe(true)
    await input.trigger("keydown", { key: "Enter", ctrlKey: true })
    await flushPromises()

    expect(api.interactions.sendMessage).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(
      "请先继续写完、保留这段，或重新生成",
      "info",
    )
    expect(input.element.value).toBe("先保存为草稿，不立即发送。")
  })

  it("重新生成只重试当前任务，不清空输入框草稿", async () => {
    const retried = deferred()
    api = makeApi({ retryAttempt: vi.fn(() => retried.promise) })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey({
          active_attempt: {
            id: "attempt-awaiting-retry",
            journey_id: journey().id,
            status: "awaiting_continue",
            visible_text: "这段尚未写完。",
          },
        }),
        llmConnections: connected(),
      },
    })
    const input = wrapper.get("textarea[aria-label='继续旅程']")
    await input.setValue("稍后还要发送的草稿")
    await wrapper.findAll(".rp-attempt-actions button")
      .find((button) => button.text() === "重新生成")
      .trigger("click")
    retried.resolve({ journey: journey(), attempt: null })
    await flushPromises()

    expect(input.element.value).toBe("稍后还要发送的草稿")
    expect(localStorage.getItem(`novel_rp_draft:${journey().id}`))
      .toBe("稍后还要发送的草稿")
  })

  it("完整刷新后同一节点的分支缓存会重新读取", async () => {
    let branchLoad = 0
    api = makeApi({
      listBranches: vi.fn(async () => {
        branchLoad += 1
        return {
          variants: branchLoad === 1
            ? [{
                node_id: "a2",
                selected: true,
                ordinal: 1,
                total: 1,
                excerpt: "原发展",
              }]
            : [
                {
                  node_id: "a2",
                  selected: true,
                  ordinal: 1,
                  total: 2,
                  excerpt: "原发展",
                },
                {
                  node_id: "a3",
                  selected: false,
                  ordinal: 2,
                  total: 2,
                  excerpt: "后来生成的其他分支",
                },
              ],
        }
      }),
      regenerate: vi.fn(async () => ({
        journey: journey({ action_options_enabled: false }),
        attempt: null,
      })),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
      },
    })
    await flushPromises()
    expect(wrapper.text()).not.toContain("其他分支 1/2")

    await wrapper.findAll(".rp-message__actions button")
      .find((button) => button.text() === "重新生成")
      .trigger("click")
    await flushPromises()

    expect(api.interactions.listBranches).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain("其他分支 1/2")
  })

  it("回顾使用固定自然分区，手工编辑受离开保护并显式保存", async () => {
    let guard = null
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
      },
      global: {
        provide: {
          [ISLAND_LEAVE_GUARD]: (fn) => {
            guard = fn
          },
        },
      },
    })
    await wrapper.findAll(".rp-composer-tools button")
      .find((button) => button.text() === "回顾")
      .trigger("click")
    await flushPromises()

    expect(wrapper.get("[aria-label='当前回顾']").text()).toContain("世界与起点")
    expect(wrapper.get("[aria-label='当前回顾']").text()).toContain("当前局面")
    expect(wrapper.html()).not.toContain("world_and_start")

    await wrapper.get("[aria-label='当前回顾'] footer button").trigger("click")
    const textareas = wrapper.findAll(".rp-overview-sections textarea")
    await textareas[2].setValue("我已经追上马车。")
    expect(guard()).toBe(true)
    await wrapper.findAll("[aria-label='当前回顾'] footer button")
      .find((button) => button.text() === "保存修改")
      .trigger("click")
    await flushPromises()

    expect(api.interactions.updateOverview).toHaveBeenCalledWith(
      journey().id,
      expect.objectContaining({
        sections: expect.objectContaining({
          current_situation: "我已经追上马车。",
        }),
        expected_overview_epoch: 0,
        expected_selection_epoch: 3,
        base_revision_id: "overview-revision-1",
        base_selected_leaf_node_id: "a2",
        base_selected_path_hash: "a".repeat(64),
      }),
    )
  })

  it("记住这一点只预填回顾，保留输入并在保存后恢复焦点", async () => {
    const wrapper = mount(InteractionView, {
      attachTo: document.body,
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
      },
    })
    try {
      const composer = wrapper.get("textarea[aria-label='继续旅程']")
      const remember = wrapper.findAll(".rp-composer-tools button")
        .find((button) => button.text() === "记住这一点")
      expect(remember.element.disabled).toBe(true)

      await composer.setValue("洛恩绝不使用火焰。")
      expect(remember.element.disabled).toBe(false)
      await remember.trigger("click")
      await flushPromises()

      const drawer = wrapper.get("[aria-label='当前回顾']")
      const mustRemember = drawer.get(
        "textarea[data-overview-section='must_remember']",
      )
      expect(mustRemember.element.value).toBe("洛恩绝不使用火焰。")
      expect(composer.element.value).toBe("洛恩绝不使用火焰。")
      expect(document.activeElement).toBe(mustRemember.element)
      expect(api.interactions.updateOverview).not.toHaveBeenCalled()
      expect(toast).toHaveBeenCalledWith(
        "已填入“必须继续记住”；确认内容后再保存。",
        "info",
      )

      await drawer.findAll("footer button")
        .find((button) => button.text() === "保存修改")
        .trigger("click")
      await flushPromises()
      expect(api.interactions.updateOverview).toHaveBeenCalledWith(
        journey().id,
        expect.objectContaining({
          sections: expect.objectContaining({
            must_remember: "洛恩绝不使用火焰。",
          }),
        }),
      )

      await drawer.get("header button").trigger("click")
      await flushPromises()
      expect(document.activeElement).toBe(remember.element)
    } finally {
      wrapper.unmount()
    }
  })

  it("记住这一点可预填当前选中的故事片段", async () => {
    const wrapper = mount(InteractionView, {
      attachTo: document.body,
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
      },
    })
    try {
      const remember = wrapper.findAll(".rp-composer-tools button")
        .find((button) => button.text() === "记住这一点")
      const storyText = wrapper.get(
        "[data-rp-message-id='a2'] .rp-message__text",
      ).element
      const range = document.createRange()
      range.selectNodeContents(storyText)
      window.getSelection().addRange(range)
      document.dispatchEvent(new Event("selectionchange"))
      await wrapper.vm.$nextTick()

      expect(remember.element.disabled).toBe(false)
      await remember.trigger("click")
      await flushPromises()

      expect(wrapper.get(
        "textarea[data-overview-section='must_remember']",
      ).element.value).toBe("最新的一段故事。")
      expect(api.interactions.updateOverview).not.toHaveBeenCalled()
    } finally {
      wrapper.unmount()
    }
  })

  it("回顾保存连点只发送一次并显示真实忙碌状态", async () => {
    const saving = deferred()
    api.interactions.updateOverview.mockReturnValue(saving.promise)
    const wrapper = mount(InteractionView, {
      props: { initialJourney: journey(), llmConnections: connected() },
    })
    await wrapper.findAll(".rp-composer-tools button")
      .find((button) => button.text() === "回顾")
      .trigger("click")
    await flushPromises()
    await wrapper.get("[aria-label='当前回顾'] footer button").trigger("click")
    await wrapper.findAll(".rp-overview-sections textarea")[2].setValue("新回顾")
    const save = wrapper.findAll("[aria-label='当前回顾'] footer button")
      .find((button) => button.text() === "保存修改")

    void save.trigger("click")
    await Promise.resolve()
    void save.trigger("click")

    expect(api.interactions.updateOverview).toHaveBeenCalledTimes(1)
    expect(save.attributes("aria-busy")).toBe("true")
    expect(save.element.disabled).toBe(true)
    saving.resolve(await makeApi().interactions.updateOverview("id", {
      sections: { current_situation: "新回顾" },
    }))
    await flushPromises()
    expect(toast).toHaveBeenCalledWith("回顾已保存", "success")
  })

  it("上下文超限时可直接查看回顾，并在首次载入时给出反馈", async () => {
    const overviewRequest = deferred()
    const overviewResult = await makeApi().interactions.getOverview()
    api.interactions.getOverview.mockReturnValue(overviewRequest.promise)
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey({
          active_attempt: {
            id: "attempt-context-budget",
            journey_id: journey().id,
            response_to_node_id: "a2",
            status: "failed",
            error_kind: "context_budget",
            visible_text: "",
            visible_offset: 0,
          },
        }),
        llmConnections: connected(),
      },
    })

    const overviewButton = wrapper.findAll(".rp-attempt-actions button")
      .find((button) => button.text() === "查看回顾")
    expect(overviewButton).toBeTruthy()
    void overviewButton.trigger("click")
    await Promise.resolve()
    expect(wrapper.get("[aria-label='当前回顾']").text()).toContain("正在载入回顾")

    overviewRequest.resolve(overviewResult)
    await flushPromises()
    expect(wrapper.get("[aria-label='当前回顾']").text()).toContain("世界与起点")
  })

  it("作品资料阻断时展示后端具体原因并可直接打开资料抽屉", async () => {
    const source = {
      revision_id: "22222222-2222-4222-8222-222222222222",
      source_title: "雾都之夜",
      version_number: 1,
      status: "ready",
      progress_label: "第一章 · 抵达雾都",
      progress_chapter_index: 1,
      progress_end_offset: 120,
      player_label: "林默",
      source_context_epoch: 2,
      update_available: false,
    }
    const object = {
      reference_key: "b".repeat(64),
      label: "林默",
      entity_type: "character",
      summary: "",
      aliases: [],
      first_chapter_index: 1,
      first_end_offset: 20,
    }
    api = makeApi({
      getSource: vi.fn(async () => ({
        id: source.revision_id,
        project_id: "11111111-1111-4111-8111-111111111111",
        title: source.source_title,
        version_number: 1,
        status: "ready",
        anchors: [],
        objects: [object],
      })),
      getJourneyReferences: vi.fn(async () => ({
        source,
        pinned: [],
        excluded: [],
        last_used: [],
      })),
      listSourceObjects: vi.fn(async () => ({ items: [object] })),
      listSources: vi.fn(async () => ({ projects: [] })),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey({
          source,
          active_attempt: {
            id: "attempt-source-blocked",
            journey_id: journey().id,
            response_to_node_id: "a2",
            status: "failed",
            error_kind: "source_context_blocked",
            error_message: "已固定的作品资料超出可用篇幅，请减少固定项",
            visible_text: "",
            visible_offset: 0,
          },
        }),
        llmConnections: connected(),
      },
    })

    const banner = wrapper.get(".rp-attempt-actions--error")
    expect(banner.text())
      .toContain("已固定的作品资料超出可用篇幅，请减少固定项")
    const sourceButton = wrapper.findAll(".rp-attempt-actions button")
      .find((button) => button.text() === "查看作品资料")
    expect(sourceButton).toBeTruthy()
    void sourceButton.trigger("click")
    await flushPromises()
    expect(wrapper.get("aside[aria-label='作品资料']").text()).toContain("雾都之夜")
  })

  it("回顾和分支历史载入失败时就地说明并提示重试", async () => {
    api.interactions.getOverview.mockRejectedValue(new Error("private overview error"))
    api.interactions.getTree.mockRejectedValue(new Error("private tree error"))
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
      },
    })

    await wrapper.findAll(".rp-composer-tools button")
      .find((button) => button.text() === "回顾")
      .trigger("click")
    await flushPromises()
    expect(wrapper.get("[aria-label='当前回顾']").text())
      .toContain("回顾暂时无法载入")
    expect(wrapper.text()).not.toContain("private overview error")
    await wrapper.get("[aria-label='当前回顾'] header button").trigger("click")

    await wrapper.findAll(".rp-more-menu > div > button")
      .find((button) => button.text() === "查看所有分支")
      .trigger("click")
    await flushPromises()
    expect(wrapper.get("[aria-label='分支历史']").text())
      .toContain("分支历史暂时无法载入")
    expect(wrapper.text()).not.toContain("private tree error")
    expect(toast).toHaveBeenCalledWith(
      "回顾暂时无法载入，请稍后重试。",
      "error",
    )
    expect(toast).toHaveBeenCalledWith(
      "分支历史暂时无法载入，请稍后重试。",
      "error",
    )
  })

  it("没有连接时仍可阅读，但生成入口就地提示且保留草稿", async () => {
    const disconnected = {
      active_provider_id: "deepseek",
      providers: [{
        provider_id: "deepseek",
        label: "DeepSeek",
        model: "deepseek-v4-flash",
        connected: false,
        active: true,
      }],
    }
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: disconnected,
      },
    })
    const input = wrapper.get("textarea[aria-label='继续旅程']")
    await input.setValue("这条草稿不能丢")

    expect(wrapper.text()).toContain("最新的一段故事")
    expect(wrapper.text()).toContain("当前模型尚未连接")
    expect(wrapper.get(".rp-send-button").element.disabled).toBe(true)
    expect(localStorage.getItem(`novel_rp_draft:${journey().id}`))
      .toBe("这条草稿不能丢")
    await wrapper.get(".rp-composer-connection button").trigger("click")
    expect(router.navigate).toHaveBeenCalledWith(
      "settings",
      null,
      true,
      expect.any(URLSearchParams),
    )
  })

  it("停止请求期间输入框仍可编辑，且不会重复提交停止", async () => {
    let finishStop
    const running = journey({
      active_attempt: {
        id: "attempt-1",
        journey_id: journey().id,
        response_to_node_id: "u2",
        status: "running",
        visible_text: "",
        visible_offset: 0,
      },
    })
    api.interactions.streamAttempt.mockImplementation(
      async function* (_journeyId, _attemptId, _offset, options) {
        await new Promise((resolve) => {
          options.signal.addEventListener("abort", resolve, { once: true })
        })
      },
    )
    api.interactions.stopAttempt.mockImplementation(() => new Promise((resolve) => {
      finishStop = resolve
    }))
    api.interactions.getJourney.mockResolvedValue(
      journey({ active_attempt: null }),
    )
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: running,
        llmConnections: connected(),
      },
    })

    await wrapper.get(".rp-stop-button").trigger("click")
    await wrapper.get("textarea[aria-label='继续旅程']").setValue("停止时先写草稿")
    expect(wrapper.text()).toContain("正在停止")
    expect(wrapper.get("textarea[aria-label='继续旅程']").element.disabled).toBe(false)
    await wrapper.get(".rp-stop-button").trigger("click")
    expect(api.interactions.stopAttempt).toHaveBeenCalledTimes(1)

    finishStop({
      attempt: { ...running.active_attempt, status: "stopped" },
      partial_node: null,
    })
    await flushPromises()
    expect(wrapper.text()).not.toContain("正在停止…")
  })

  it("停止失败时保留生成状态且不展示后端原始诊断", async () => {
    let releaseStream
    const running = journey({
      active_attempt: {
        id: "attempt-stop-failure",
        journey_id: journey().id,
        response_to_node_id: "u2",
        status: "running",
        visible_text: "仍在生成的正文。",
        visible_offset: 8,
      },
    })
    api.interactions.streamAttempt.mockImplementation(
      async function* (_journeyId, _attemptId, _offset, options) {
        await new Promise((resolve) => {
          releaseStream = resolve
          options.signal.addEventListener("abort", resolve, { once: true })
        })
        if (false) yield null
      },
    )
    api.interactions.stopAttempt.mockRejectedValue(
      new Error("API /attempts/private-uuid/stop failed (500)"),
    )
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: running,
        llmConnections: connected(),
      },
    })
    await flushPromises()

    await wrapper.get(".rp-stop-button").trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("仍在生成的正文。")
    expect(api.interactions.streamAttempt).toHaveBeenCalledWith(
      journey().id,
      "attempt-stop-failure",
      8,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(wrapper.text()).not.toContain("private-uuid")
    expect(toast).toHaveBeenCalledWith(
      "停止请求暂时失败；故事仍在生成，请重试。",
      "error",
    )

    wrapper.unmount()
    releaseStream?.()
  })

  it("显式离开故事页会立即撤销看海前台授权", async () => {
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey({ see_sea_enabled: true }),
        llmConnections: connected(),
      },
    })

    wrapper.unmount()
    await flushPromises()

    expect(api.interactions.leaveJourney).toHaveBeenCalledOnce()
    expect(api.interactions.leaveJourney).toHaveBeenCalledWith(journey().id)
  })

  it("离页后不会因迟到的首次确认开启看海", async () => {
    const acknowledgement = deferred()
    api = makeApi({
      acknowledgeSeeSeaNotice: vi.fn(() => acknowledgement.promise),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
        preferences: { see_sea_notice_acknowledged: false },
      },
    })

    await wrapper.findAll(".rp-mode-toggle")
      .find((button) => button.text() === "故事自主发展")
      .trigger("click")
    const confirmButton = [...document.querySelectorAll(".rp-sea-notice button")]
      .find((button) => button.textContent === "开始自主发展")
    confirmButton.click()
    await Promise.resolve()
    wrapper.unmount()

    acknowledgement.resolve({ see_sea_notice_acknowledged: true })
    await flushPromises()

    expect(api.interactions.updateModes).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it("看海开启响应晚于离页时补发撤销且不继续生成", async () => {
    const update = deferred()
    api = makeApi({ updateModes: vi.fn(() => update.promise) })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
        preferences: { see_sea_notice_acknowledged: true },
      },
    })

    await wrapper.findAll(".rp-mode-toggle")
      .find((button) => button.text() === "故事自主发展")
      .trigger("click")
    await Promise.resolve()
    wrapper.unmount()

    update.resolve({
      journey: journey({ see_sea_enabled: true }),
      attempt: { id: "late-attempt", status: "pending" },
    })
    await flushPromises()

    expect(api.interactions.leaveJourney).toHaveBeenCalledOnce()
    expect(api.interactions.leaveJourney).toHaveBeenCalledWith(journey().id)
    expect(api.interactions.streamAttempt).not.toHaveBeenCalled()
  })

  it("归档旅程响应晚于离页时不再导航或提示", async () => {
    const archive = deferred()
    api = makeApi({ archiveJourney: vi.fn(() => archive.promise) })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: { initialJourney: journey(), llmConnections: connected() },
    })

    await wrapper.findAll(".rp-more-menu > div > button")
      .find((button) => button.text() === "归档旅程")
      .trigger("click")
    await Promise.resolve()
    wrapper.unmount()

    archive.resolve({ archived: true })
    await flushPromises()

    expect(api.interactions.archiveJourney).toHaveBeenCalledOnce()
    expect(router.navigate).not.toHaveBeenCalledWith("journeys")
    expect(toast).not.toHaveBeenCalled()
  })

  it.each([
    ["成功", ""],
    ["失败", "离页前仍要保留的草稿"],
  ])("发送%s响应晚于离页时正确收口本地草稿", async (outcome, expectedDraft) => {
    const send = deferred()
    api = makeApi({ sendMessage: vi.fn(() => send.promise) })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: { initialJourney: journey(), llmConnections: connected() },
    })
    const composer = wrapper.get("textarea[aria-label='继续旅程']")
    await composer.setValue("离页前仍要保留的草稿")
    await wrapper.get(".rp-send-button").trigger("click")
    await vi.waitFor(() => expect(api.interactions.sendMessage).toHaveBeenCalledOnce())

    wrapper.unmount()
    if (outcome === "成功") {
      send.resolve({
        journey: journey({ selection_epoch: 4 }),
        attempt: { id: "late-send-attempt", status: "pending", visible_text: "" },
      })
    } else {
      send.reject(new Error("late private failure"))
    }
    await flushPromises()

    expect(localStorage.getItem(`novel_rp_draft:${journey().id}`))
      .toBe(expectedDraft || null)
    expect(api.interactions.streamAttempt).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it("发送响应晚于分支切换时不覆盖新分支、草稿或生成跟随", async () => {
    const send = deferred()
    const selectedBranch = journey({
      selection_epoch: 4,
      selected_leaf_node_id: "a1",
      messages: [
        message("u-branch", "user", "我选择另一条路。"),
        message("a1", "assistant", "新分支正文。"),
      ],
    })
    const staleSendJourney = journey({
      selection_epoch: 4,
      selected_leaf_node_id: "a-old-send",
      messages: [
        message("u-old-send", "user", "旧分支发送。"),
        message("a-old-send", "assistant", "旧发送响应正文。"),
      ],
    })
    api = makeApi({
      getJourney: vi.fn(async () => staleSendJourney),
      listBranches: vi.fn(async () => ({
        variants: [
          { node_id: "a1", selected: false, ordinal: 1, total: 2, excerpt: "转向另一条路。" },
          { node_id: "a2", selected: true, ordinal: 2, total: 2, excerpt: "最新的一段故事。" },
        ],
      })),
      selectBranch: vi.fn(async () => selectedBranch),
      sendMessage: vi.fn(() => send.promise),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: { initialJourney: journey(), llmConnections: connected() },
    })
    await vi.waitFor(() => expect(wrapper.text()).toContain("其他分支 2/2"))
    await wrapper.findAll(".rp-message__actions button")
      .find((button) => button.text() === "其他分支 2/2")
      .trigger("click")

    const composer = wrapper.get("textarea[aria-label='继续旅程']")
    await composer.setValue("原分支待发送内容")
    await wrapper.get(".rp-send-button").trigger("click")
    await vi.waitFor(() => expect(api.interactions.sendMessage).toHaveBeenCalledOnce())
    await wrapper.findAll(".rp-branch-popover button")
      .find((button) => button.text().includes("转向另一条路"))
      .trigger("click")
    await flushPromises()
    await composer.setValue("新分支继续写的草稿")

    send.resolve({
      journey: staleSendJourney,
      attempt: { id: "stale-branch-attempt", status: "pending", visible_text: "" },
    })
    await flushPromises()

    expect(wrapper.text()).toContain("新分支正文。")
    expect(wrapper.text()).not.toContain("旧发送响应正文。")
    expect(composer.element.value).toBe("新分支继续写的草稿")
    expect(localStorage.getItem(`novel_rp_draft:${journey().id}`))
      .toBe("新分支继续写的草稿")
    expect(api.interactions.streamAttempt).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("生成或等待续写时不允许切换分支", async () => {
    const running = journey({
      active_attempt: {
        id: "attempt-branch",
        journey_id: journey().id,
        response_to_node_id: "u2",
        status: "running",
        visible_text: "",
        visible_offset: 0,
      },
    })
    api.interactions.streamAttempt.mockImplementation(async function* () {
      await new Promise(() => {})
    })
    api.interactions.listBranches.mockResolvedValue({
      variants: [
        {
          node_id: "a2",
          selected: true,
          ordinal: 1,
          total: 2,
          excerpt: "当前发展",
        },
        {
          node_id: "a3",
          selected: false,
          ordinal: 2,
          total: 2,
          excerpt: "另一发展",
        },
      ],
    })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: running,
        llmConnections: connected(),
      },
    })
    await flushPromises()
    await wrapper.findAll(".rp-message__actions button")
      .find((button) => button.text().startsWith("其他分支"))
      .trigger("click")
    await flushPromises()

    const variants = wrapper.findAll(".rp-branch-popover button")
    expect(variants).toHaveLength(2)
    expect(variants.every((button) => button.element.disabled)).toBe(true)
  })

  it("返回故事页时会按旧锚点加载 recent window 之外的阅读位置", async () => {
    sessionStorage.setItem(
      `novel_rp_scroll:${journey().id}`,
      JSON.stringify({ anchorId: "a0", scrollTop: 720, atBottom: false }),
    )
    api.interactions.getMessages.mockResolvedValue({
      items: [
        message("u0", "user", "更早的行动。"),
        message("a0", "assistant", "很久以前的故事。"),
      ],
      has_older: false,
      has_newer: true,
      selection_epoch: 3,
    })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
        initialPathIndex: {
          selection_epoch: 3,
          items: [
            { id: "a0", ordinal: 1, total: 3, excerpt: "很久以前的故事。" },
            { id: "a1", ordinal: 2, total: 3, excerpt: "旧的一段故事。" },
            { id: "a2", ordinal: 3, total: 3, excerpt: "最新的一段故事。" },
          ],
        },
      },
    })
    await flushPromises()

    expect(api.interactions.getMessages).toHaveBeenCalledWith(
      journey().id,
      { around_node_id: "a0", limit: 20 },
    )
    expect(wrapper.text()).toContain("很久以前的故事")
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
  })

  it("切换分支后定位到分岔处，而不是强制跳到分支末尾", async () => {
    api.interactions.listBranches.mockResolvedValue({
      variants: [
        {
          node_id: "a2",
          selected: true,
          ordinal: 1,
          total: 2,
          excerpt: "当前发展",
        },
        {
          node_id: "a9",
          selected: false,
          ordinal: 2,
          total: 2,
          excerpt: "钟声方向",
        },
      ],
    })
    api.interactions.selectBranch.mockResolvedValue(journey({
      selection_epoch: 4,
      selected_leaf_node_id: "a10",
      messages: [
        message("u1", "user", "我推开门。"),
        message("a9", "assistant", "我转向钟声传来的方向。"),
        message("u9", "user", "我继续调查。"),
        message("a10", "assistant", "很久以后，我抵达了塔顶。"),
      ],
    }))
    api.interactions.getPathIndex.mockResolvedValue({
      selection_epoch: 4,
      items: [
        { id: "a9", ordinal: 1, total: 2, excerpt: "钟声方向" },
        { id: "a10", ordinal: 2, total: 2, excerpt: "抵达塔顶" },
      ],
    })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
      },
    })
    await flushPromises()
    await wrapper.findAll(".rp-message__actions button")
      .find((button) => button.text().startsWith("其他分支"))
      .trigger("click")
    await flushPromises()
    await wrapper.findAll(".rp-branch-popover button")
      .find((button) => button.text().includes("钟声方向"))
      .trigger("click")
    await flushPromises()

    const lastContext = Element.prototype.scrollIntoView.mock.contexts.at(-1)
    expect(lastContext.dataset.rpMessageId).toBe("a9")
  })

  it("更多操作提供主题和关闭语义，执行后立即收起", async () => {
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
      },
      attachTo: document.body,
    })
    const requestedThemes = []
    wrapper.element.addEventListener("shell-theme-request", (event) => {
      requestedThemes.push(event.detail)
    })
    const menu = wrapper.get(".rp-more-menu")
    menu.element.open = true

    expect(menu.get(".rp-more-menu__header button").attributes("aria-label"))
      .toBe("关闭更多操作")
    expect(menu.text()).toContain("晨光便签")
    expect(menu.text()).toContain("暗夜书房")
    expect(menu.text()).toContain("水墨写意")
    expect(menu.get('.rp-more-menu__themes [role="menu"]').attributes("aria-label"))
      .toBe("选择阅读主题")
    const themeItems = menu.findAll('[role="menuitemradio"]')
    expect(themeItems[0].attributes("aria-checked")).toBe("true")
    expect(themeItems[1].attributes("aria-checked")).toBe("false")
    expect(themeItems.map((item) => item.attributes("tabindex"))).toEqual(["0", "-1", "-1"])
    themeItems[0].element.focus()
    await themeItems[0].trigger("keydown", { key: "ArrowDown" })
    expect(document.activeElement).toBe(themeItems[1].element)
    expect(themeItems.map((item) => item.attributes("tabindex"))).toEqual(["-1", "0", "-1"])
    await themeItems[1].trigger("keydown", { key: "Escape" })
    await flushPromises()
    expect(menu.element.open).toBe(false)
    expect(document.activeElement).toBe(menu.get("summary").element)

    menu.element.open = true
    await menu.findAll(".rp-more-menu__themes button")
      .find((button) => button.text().includes("暗夜书房"))
      .trigger("click")
    await flushPromises()

    expect(requestedThemes).toEqual(["night"])
    expect(menu.element.open).toBe(false)
    expect(menu.get('[data-theme-value="night"]').attributes("aria-checked")).toBe("true")
    expect(document.activeElement).toBe(menu.get("summary").element)
    wrapper.unmount()
  })

  it("短历史显示逐段刻度，点击仍使用完整路径定位接口", async () => {
    api.interactions.getMessages.mockResolvedValue({
      items: [message("a0", "assistant", "最早的一段故事。")],
      has_older: false,
      has_newer: true,
      selection_epoch: 3,
    })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
        initialPathIndex: {
          selection_epoch: 3,
          items: [
            { id: "a0", ordinal: 1, total: 3, excerpt: "最早的一段故事。" },
            { id: "a1", ordinal: 2, total: 3, excerpt: "旧的一段故事。" },
            { id: "a2", ordinal: 3, total: 3, excerpt: "最新的一段故事。" },
          ],
        },
      },
    })

    const ticks = wrapper.findAll(".rp-locator-ticks button")
    expect(ticks).toHaveLength(3)
    await wrapper.get(".rp-locator-rail").trigger("pointerdown")
    expect(wrapper.get(".rp-locator-rail").classes()).toContain("is-expanded")
    await ticks[0].trigger("click")
    await flushPromises()

    expect(api.interactions.getMessages).toHaveBeenCalledWith(
      journey().id,
      { around_node_id: "a0", limit: 20 },
    )
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
    expect(wrapper.get(".rp-locator-rail").classes()).not.toContain("is-expanded")
  })

  it("完整分支树默认聚焦最近分岔，可按需展开更早分岔", async () => {
    api.interactions.getTree.mockResolvedValue({
      branch_points: [
        { parent_node_id: "p1", label: "最早分岔", variants: [] },
        { parent_node_id: "p2", label: "中间分岔", variants: [] },
        {
          parent_node_id: "p3",
          label: "最近分岔",
          variants: [
            { node_id: "a2", selected: true, excerpt: "继续追查钟楼" },
            { node_id: "a9", selected: false, excerpt: "转向旧港口" },
          ],
        },
      ],
    })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
      },
    })
    await wrapper.findAll(".rp-more-menu > div > button")
      .find((button) => button.text() === "查看所有分支")
      .trigger("click")
    await flushPromises()

    expect(wrapper.findAll(".rp-tree-branch")).toHaveLength(1)
    expect(wrapper.get(".rp-tree-branch").text()).toContain("最近分岔")
    expect(wrapper.get(".rp-tree-branch").findAll("button")
      .find((button) => button.text().includes("继续追查钟楼"))
      .attributes("aria-pressed")).toBe("true")
    expect(wrapper.get(".rp-tree-branch").findAll("button")
      .find((button) => button.text().includes("转向旧港口"))
      .attributes("aria-pressed")).toBe("false")
    await wrapper.get(".rp-tree-expand").trigger("click")
    expect(wrapper.findAll(".rp-tree-branch")).toHaveLength(3)
    expect(wrapper.text()).toContain("最早分岔")
  })

  it("失败回顾可重试，未选中的失败残段从生成记录显式采用", async () => {
    api.interactions.getOverview.mockResolvedValue({
      ...(await makeApi().interactions.getOverview()),
      status: "failed",
    })
    api.interactions.retryOverview.mockResolvedValue({
      ...(await makeApi().interactions.getOverview()),
      status: "refreshing",
      is_refreshing: true,
    })
    api.interactions.listGenerationRecords.mockResolvedValue({
      items: [{
        id: "failed-record-1",
        visible_text: "雨幕中只写到一半的段落。",
        error_kind: "connection",
        created_at: "2026-07-28T00:00:00Z",
      }],
    })
    api.interactions.keepAttempt.mockResolvedValue({})
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
      },
    })

    await wrapper.findAll(".rp-composer-tools button")
      .find((button) => button.text() === "回顾")
      .trigger("click")
    await flushPromises()
    await wrapper.findAll("[aria-label='当前回顾'] footer button")
      .find((button) => button.text() === "重新整理")
      .trigger("click")
    await flushPromises()
    expect(api.interactions.retryOverview).toHaveBeenCalledWith(journey().id)

    await wrapper.findAll(".rp-more-menu > div > button")
      .find((button) => button.text() === "生成记录")
      .trigger("click")
    await flushPromises()
    expect(wrapper.get("[aria-label='生成记录']").text())
      .toContain("雨幕中只写到一半")
    await wrapper.findAll("[aria-label='生成记录'] button")
      .find((button) => button.text() === "保留这段")
      .trigger("click")
    await flushPromises()

    expect(api.interactions.keepAttempt).toHaveBeenCalledWith(
      journey().id,
      "failed-record-1",
      { expected_selection_epoch: 3 },
    )
  })

  it("为抽屉加载、失败与关闭操作公开对应的语义", async () => {
    const overviewLoad = deferred()
    api.interactions.getOverview.mockReturnValue(overviewLoad.promise)
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
      },
    })

    await wrapper.findAll(".rp-composer-tools button")
      .find((button) => button.text() === "回顾")
      .trigger("click")
    await Promise.resolve()
    const overviewDrawer = wrapper.get("[aria-label='当前回顾']")
    expect(overviewDrawer.attributes("aria-busy")).toBe("true")
    expect(overviewDrawer.get(".rp-overview-empty").attributes("role")).toBe("status")
    expect(overviewDrawer.get("header button").attributes("aria-label")).toBe("关闭当前回顾")

    overviewLoad.resolve(await makeApi().interactions.getOverview())
    await flushPromises()
    expect(overviewDrawer.attributes("aria-busy")).toBe("false")
    await overviewDrawer.get("header button").trigger("click")

    await wrapper.findAll(".rp-more-menu > div > button")
      .find((button) => button.text() === "生成记录")
      .trigger("click")
    await flushPromises()
    expect(wrapper.get("[aria-label='生成记录'] header button").attributes("aria-label"))
      .toBe("关闭生成记录")

    await wrapper.findAll(".rp-more-menu > div > button")
      .find((button) => button.text() === "查看所有分支")
      .trigger("click")
    await flushPromises()
    expect(wrapper.get("[aria-label='分支历史'] header button").attributes("aria-label"))
      .toBe("关闭分支历史")

    await wrapper.findAll(".rp-more-menu > div > button")
      .find((button) => button.text() === "内容与数据")
      .trigger("click")
    expect(wrapper.get("[aria-label='内容与数据'] header button").attributes("aria-label"))
      .toBe("关闭内容与数据")
  })

  it("关闭回顾后切换分支并重开时只接受新抽屉的响应", async () => {
    const staleOverview = deferred()
    const baseOverview = await makeApi().interactions.getOverview()
    const selectedBranch = journey({
      selection_epoch: 4,
      selected_leaf_node_id: "a1",
      messages: [
        message("u-branch", "user", "我选择另一条路。"),
        message("a1", "assistant", "新分支正文。"),
      ],
    })
    api = makeApi({
      listBranches: vi.fn(async () => ({
        variants: [
          { node_id: "a1", selected: false, ordinal: 1, total: 2, excerpt: "转向另一条路。" },
          { node_id: "a2", selected: true, ordinal: 2, total: 2, excerpt: "最新的一段故事。" },
        ],
      })),
      selectBranch: vi.fn(async () => selectedBranch),
    })
    api.interactions.getOverview
      .mockImplementationOnce(() => staleOverview.promise)
      .mockResolvedValueOnce({
        ...baseOverview,
        sections: {
          ...baseOverview.sections,
          current_situation: "新分支回顾。",
        },
        anchor_node_id: "a1",
        base_selected_leaf_node_id: "a1",
        base_selected_path_hash: "c".repeat(64),
      })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: { initialJourney: journey(), llmConnections: connected() },
    })
    await vi.waitFor(() => expect(wrapper.text()).toContain("其他分支 2/2"))

    await wrapper.findAll(".rp-composer-tools button")
      .find((button) => button.text() === "回顾")
      .trigger("click")
    await vi.waitFor(() => expect(api.interactions.getOverview).toHaveBeenCalledTimes(1))
    await wrapper.get("[aria-label='当前回顾'] header button").trigger("click")

    await wrapper.findAll(".rp-message__actions button")
      .find((button) => button.text() === "其他分支 2/2")
      .trigger("click")
    await wrapper.findAll(".rp-branch-popover button")
      .find((button) => button.text().includes("转向另一条路"))
      .trigger("click")
    await flushPromises()

    await wrapper.findAll(".rp-composer-tools button")
      .find((button) => button.text() === "回顾")
      .trigger("click")
    await vi.waitFor(() => expect(api.interactions.getOverview).toHaveBeenCalledTimes(2))
    await flushPromises()
    expect(wrapper.get("[aria-label='当前回顾']").text()).toContain("新分支回顾。")

    staleOverview.resolve({
      ...baseOverview,
      sections: {
        ...baseOverview.sections,
        current_situation: "旧分支迟到的回顾。",
      },
    })
    await flushPromises()

    expect(wrapper.get("[aria-label='当前回顾']").text()).toContain("新分支回顾。")
    expect(wrapper.get("[aria-label='当前回顾']").text()).not.toContain("旧分支迟到的回顾。")
    expect(toast).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("为准备和实际失败的故事状态公开状态角色", () => {
    const preparing = mount(InteractionView, {
      props: {
        initialJourney: journey({
          active_attempt: {
            id: "attempt-preparing",
            journey_id: journey().id,
            status: "preparing_context",
            visible_text: "",
          },
        }),
        llmConnections: connected(),
      },
    })
    expect(preparing.get(".rp-message--streaming").attributes("aria-busy")).toBe("true")
    expect(preparing.get(".rp-message--streaming .rp-message__label").text()).toContain("正在生成")
    expect(preparing.get(".rp-stream-status").attributes("role")).toBe("status")
    preparing.unmount()

    const partial = mount(InteractionView, {
      props: {
        initialJourney: journey({
          active_attempt: {
            id: "attempt-partial",
            journey_id: journey().id,
            status: "awaiting_continue",
            visible_text: "这一段还没有写完。",
          },
        }),
        llmConnections: connected(),
      },
    })
    expect(partial.get(".rp-message--streaming .rp-message__label").text()).toContain("未完成")
    partial.unmount()

    const failed = mount(InteractionView, {
      props: {
        initialJourney: journey({
          active_attempt: { id: "attempt-failed", status: "failed", error_kind: "connection" },
        }),
        llmConnections: connected(),
      },
    })
    expect(failed.get(".rp-attempt-actions--error").attributes("role")).toBe("alert")
  })

  it("停止生成期间公开状态通告", async () => {
    const stopRequest = deferred()
    const streamWait = deferred()
    api = makeApi({
      stopAttempt: vi.fn(() => stopRequest.promise),
      streamAttempt: vi.fn(async function* () {
        await streamWait.promise
      }),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey({
          active_attempt: {
            id: "attempt-stopping",
            journey_id: journey().id,
            status: "running",
            visible_text: "",
          },
        }),
        llmConnections: connected(),
      },
    })
    await Promise.resolve()

    void wrapper.get(".rp-stop-button").trigger("click")
    await Promise.resolve()
    expect(wrapper.get(".rp-composer-dock .rp-stream-status").attributes("role"))
      .toBe("status")

    stopRequest.resolve({ attempt: { id: "attempt-stopping", status: "cancelled" } })
    streamWait.resolve()
    await flushPromises()
  })

  it("归档请求失败时保留当前流连接并给出可恢复提示", async () => {
    let streamSignal
    let releaseStream
    api = makeApi({
      archiveJourney: vi.fn().mockRejectedValue(new Error("offline")),
      streamAttempt: vi.fn(async function* (_journeyId, _attemptId, _offset, options) {
        streamSignal = options.signal
        await new Promise((resolve) => {
          releaseStream = resolve
          options.signal.addEventListener("abort", resolve, { once: true })
        })
        if (false) yield null
      }),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey({
          active_attempt: {
            id: "running-attempt",
            status: "running",
            visible_text: "仍在生成的正文。",
          },
        }),
        llmConnections: connected(),
      },
    })
    await flushPromises()

    await wrapper.findAll(".rp-more-menu > div > button")
      .find((button) => button.text() === "归档旅程")
      .trigger("click")
    await flushPromises()

    expect(api.interactions.archiveJourney).toHaveBeenCalledWith(journey().id)
    expect(streamSignal.aborted).toBe(false)
    expect(router.navigate).not.toHaveBeenCalledWith("journeys")
    expect(toast).toHaveBeenCalledWith(
      "归档失败；旅程和正在生成的内容仍保留，请重试。",
      "error",
    )

    wrapper.unmount()
    releaseStream?.()
  })

  it("保留截断内容失败时不清空已显示正文", async () => {
    api.interactions.keepAttempt.mockRejectedValue(new Error("offline"))
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey({
          active_attempt: {
            id: "awaiting-attempt",
            status: "awaiting_continue",
            visible_text: "已经显示但尚未写完的正文。",
          },
        }),
        llmConnections: connected(),
      },
    })

    await wrapper.findAll(".rp-attempt-actions button")
      .find((button) => button.text() === "保留这段")
      .trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("已经显示但尚未写完的正文。")
    expect(toast).toHaveBeenCalledWith(
      "暂时无法保留这段；已生成的内容仍在，请重试。",
      "error",
    )
  })

  it("流结束后刷新失败时保留已显示正文并提供明确恢复路径", async () => {
    api = makeApi({
      getJourney: vi.fn().mockRejectedValue(new Error("offline")),
      streamAttempt: vi.fn(async function* () {
        yield {
          event: "chunk",
          data: { text: "已经写到浏览器里的故事。", offset: 12 },
        }
        yield {
          event: "status",
          data: { status: "completed" },
        }
      }),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey({
          active_attempt: {
            id: "completed-before-refresh",
            status: "running",
            visible_text: "",
          },
        }),
        llmConnections: connected(),
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain("已经写到浏览器里的故事。")
    expect(wrapper.text()).toContain(
      "故事已保存，但最新状态暂时无法载入；已显示内容仍保留，请刷新页面重试。",
    )
  })

  it("载入冲突后的最新发展失败时不丢失冲突操作和输入", async () => {
    const selectionConflict = Object.assign(new Error("conflict"), {
      status: 409,
      body: {
        error: "interaction_selection_conflict",
        context: { current_selection_epoch: 4 },
      },
    })
    api = makeApi({
      sendMessage: vi.fn().mockRejectedValue(selectionConflict),
      getJourney: vi.fn().mockRejectedValue(new Error("offline")),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey(),
        llmConnections: connected(),
      },
    })
    const composer = wrapper.get("textarea[aria-label='继续旅程']")
    await composer.setValue("我仍要从门边继续。")
    await wrapper.get(".rp-send-button").trigger("click")
    await flushPromises()

    expect(wrapper.find(".rp-conflict-banner").exists()).toBe(true)
    await wrapper.findAll(".rp-conflict-banner button")
      .find((button) => button.text() === "载入最新发展")
      .trigger("click")
    await flushPromises()

    expect(wrapper.find(".rp-conflict-banner").exists()).toBe(true)
    expect(composer.element.value).toBe("我仍要从门边继续。")
    expect(toast).toHaveBeenCalledWith(
      "最新发展暂时无法载入；你的输入仍保留，请重试。",
      "error",
    )
  })

  it("冲突后继续使用输入框最新内容，并只在成功后清空", async () => {
    const selectionConflict = Object.assign(new Error("conflict"), {
      status: 409,
      body: {
        error: "interaction_selection_conflict",
        context: { current_selection_epoch: 4 },
      },
    })
    api = makeApi({
      sendMessage: vi.fn().mockRejectedValue(selectionConflict),
      continueFromNode: vi.fn(async () => ({ journey: journey({ selection_epoch: 4 }), attempt: null })),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: { initialJourney: journey(), llmConnections: connected() },
    })
    const composer = wrapper.get("textarea[aria-label='继续旅程']")
    await composer.setValue("触发冲突的旧内容")
    await wrapper.get(".rp-send-button").trigger("click")
    await flushPromises()
    await composer.setValue("冲突后重新整理的新内容")

    await wrapper.findAll(".rp-conflict-banner button")
      .find((button) => button.text() === "仍从我看到的位置继续")
      .trigger("click")
    await flushPromises()

    expect(api.interactions.continueFromNode).toHaveBeenCalledWith(
      journey().id,
      "a2",
      expect.objectContaining({ content: "冲突后重新整理的新内容", expected_selection_epoch: 4 }),
    )
    expect(composer.element.value).toBe("")
  })

  it("从更多操作打开作品资料，显示本轮理由并带 epoch 固定对象", async () => {
    const source = {
      revision_id: "22222222-2222-4222-8222-222222222222",
      source_title: "雾都之夜",
      version_number: 1,
      status: "ready",
      progress_label: "第一章 · 抵达雾都",
      progress_chapter_index: 1,
      progress_end_offset: 120,
      player_label: "林默",
      source_context_epoch: 2,
      update_available: false,
    }
    const object = {
      reference_key: "b".repeat(64),
      label: "林默",
      entity_type: "character",
      summary: "",
      aliases: [],
      first_chapter_index: 1,
      first_end_offset: 20,
    }
    api = makeApi({
      getSource: vi.fn(async () => ({
        id: source.revision_id,
        project_id: "11111111-1111-4111-8111-111111111111",
        title: source.source_title,
        version_number: 1,
        status: "ready",
        anchors: [],
        objects: [object],
      })),
      getJourneyReferences: vi.fn(async () => ({
        source,
        pinned: [],
        excluded: [],
        last_used: [{ label: "林默", reason: "本轮提到" }],
      })),
      listSourceObjects: vi.fn(async () => ({ items: [object] })),
      listSources: vi.fn(async () => ({ projects: [] })),
      updateJourneyReferences: vi.fn(async () => ({
        source: { ...source, source_context_epoch: 3 },
        pinned: [object],
        excluded: [],
        last_used: [],
      })),
    })
    setBridgeOverrides({ api, router, toast, confirm, prompt: vi.fn() })
    const wrapper = mount(InteractionView, {
      props: {
        initialJourney: journey({ source }),
        llmConnections: connected(),
      },
    })

    await wrapper.findAll(".rp-more-menu button")
      .find((button) => button.text() === "作品资料")
      .trigger("click")
    await flushPromises()

    expect(wrapper.get("aside[aria-label='作品资料']").text()).toContain("本轮提到")
    expect(api.interactions.listSourceObjects).toHaveBeenCalledWith(
      source.revision_id,
      { chapter_index: 1, end_offset: 120 },
    )
    await wrapper.findAll(".rp-source-object-list button")
      .find((button) => button.text() === "固定")
      .trigger("click")
    await flushPromises()
    expect(api.interactions.updateJourneyReferences).toHaveBeenCalledWith(
      journey().id,
      {
        action: "pin",
        reference_key: object.reference_key,
        expected_source_context_epoch: 2,
      },
    )
  })
})
