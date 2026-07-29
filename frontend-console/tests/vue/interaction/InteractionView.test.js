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
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
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
  resetBridgeOverrides()
  vi.restoreAllMocks()
})

describe("RP 故事页", () => {
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

    expect(wrapper.get(".rp-action-options button").text())
      .toBe("我立刻追上去。")
    const branchButton = wrapper.findAll(".rp-message__actions button")
      .find((button) => button.text() === "其他分支 2/2")
    expect(branchButton).toBeTruthy()
    await branchButton.trigger("click")

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
    })
    const requestedThemes = []
    wrapper.element.addEventListener("shell-theme-request", (event) => {
      requestedThemes.push(event.detail)
    })
    const menu = wrapper.get(".rp-more-menu")
    menu.element.open = true

    expect(menu.text()).toContain("现代极简")
    expect(menu.text()).toContain("黄金时刻")
    expect(menu.text()).toContain("午夜星河")
    await menu.findAll(".rp-more-menu__themes button")
      .find((button) => button.text().includes("午夜星河"))
      .trigger("click")

    expect(requestedThemes).toEqual(["dark"])
    expect(menu.element.open).toBe(false)
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
        { parent_node_id: "p3", label: "最近分岔", variants: [] },
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
})
