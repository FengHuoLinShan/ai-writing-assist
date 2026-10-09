/**
 * 新书开篇引导流程卡（BR-5）：开始输入 → 方向卡选择（可改字段、再要一批）
 * → 骨架逐条取舍与采用 → 「骨架可用」的三个去向。作者语言，不暴露内部标识。
 */
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import OpeningFlowCard from "../../../vue/views/today/components/OpeningFlowCard.vue"

enableAutoUnmount(afterEach)

const CHOOSE_STOP = {
  step_id: "choose_direction",
  kind: "author_choice",
  reason: "从方向卡里选一张，可直接修改字段；都不满意可以再要一批。",
  actions: [
    { action: "more_cards", label: "再要一批方向卡" },
    { action: "abandon_flow", label: "结束流程" },
  ],
}

function cardView(overrides = {}) {
  return {
    run_id: "run-1",
    flow_id: "new_book_opening",
    flow_version: 1,
    title: "新书开篇",
    status: "waiting_approval",
    stop: CHOOSE_STOP,
    steps: [
      { step_id: "direction_cards", title: "生成方向卡", state: "done", detail: "" },
      { step_id: "choose_direction", title: "选择方向", state: "active", detail: "" },
    ],
    panel: {
      vision: "潮汐城市",
      batch: 1,
      more_allowed: true,
      cards: [
        {
          title: "潮汐都市",
          genre_promise: "城市奇幻",
          central_conflict: "潮钟权柄之争",
          protagonist_goal: "找回被收走的名字",
          world_tone: "潮湿、明亮",
          reader_promise: "每章解开一层规则",
          main_risk: "设定密度偏高",
        },
        {
          title: "守灯人",
          genre_promise: "温情奇幻",
          central_conflict: "灯塔熄灭倒计时",
          protagonist_goal: "在天亮前续上灯油",
          world_tone: "安静、克制",
          reader_promise: "情感厚重",
          main_risk: "冲突尺度偏小",
        },
      ],
      chosen: null,
      package: null,
      adopted: null,
    },
    settings: {},
    ...overrides,
  }
}

let apiMock
let navigate

beforeEach(() => {
  navigate = vi.fn()
  apiMock = {
    assistant: {
      guidedFlowStart: vi.fn(async () => cardView()),
      guidedFlowActive: vi.fn(async () => null),
      guidedFlow: vi.fn(async (_projectId, runId) => views[runId] || cardView()),
      guidedFlowAdvance: vi.fn(async () => cardView()),
      guidedFlowAbandon: vi.fn(async () => ({ status: "cancelled" })),
    },
  }
  const views = {}
  apiMock.views = views
  setBridgeOverrides({
    api: apiMock,
    router: { navigate, refresh: vi.fn(() => true) },
    toast: vi.fn(),
    state: { currentProjectId: "p1" },
  })
})

afterEach(() => resetBridgeOverrides())

async function mountCard() {
  const wrapper = mount(OpeningFlowCard, {
    props: { projectId: "p1", available: true },
  })
  await flushPromises()
  return wrapper
}

describe("OpeningFlowCard（新书开篇引导卡）", () => {
  it("不可用时完全不渲染", async () => {
    const wrapper = mount(OpeningFlowCard, {
      props: { projectId: "p1", available: false },
    })
    await flushPromises()
    expect(wrapper.find(".opening-flow").exists()).toBe(false)
  })

  it("开始携带一句构想与可选意向，并立即推进生成方向卡", async () => {
    const wrapper = await mountCard()
    await wrapper.get('[data-action="opening-vision"]').setValue("潮汐城市")
    await wrapper.get('[data-action="opening-start"]').trigger("click")
    await flushPromises()
    expect(apiMock.assistant.guidedFlowStart).toHaveBeenCalledWith({
      novel_id: "p1",
      flow_id: "new_book_opening",
      input: { vision: "潮汐城市" },
    })
    expect(apiMock.assistant.guidedFlowAdvance).toHaveBeenCalledWith("run-1", {
      novel_id: "p1",
    })
    expect(wrapper.text()).toContain("潮汐都市")
    expect(wrapper.text()).toContain("题材承诺")
    expect(wrapper.text()).not.toContain("new_book_opening")
  })

  it("方向停点：选卡可改字段后继续；再要一批走新调用", async () => {
    apiMock.assistant.guidedFlowActive.mockResolvedValue(cardView())
    apiMock.views["run-1"] = cardView()
    const wrapper = await mountCard()
    await wrapper.findAll('[data-action="opening-pick-card"]')[0].setValue(true)
    const areas = wrapper.findAll(".opening-flow__fields textarea")
    expect(areas.length).toBe(6)
    await areas[1].setValue("改后的主冲突")
    await wrapper.get('[data-action="opening-choose-direction"]').trigger("click")
    await flushPromises()
    expect(apiMock.assistant.guidedFlowAdvance).toHaveBeenLastCalledWith("run-1", {
      novel_id: "p1",
      choice: {
        step_id: "choose_direction",
        action: "choose",
        card_index: 0,
        fields: expect.objectContaining({ central_conflict: "改后的主冲突" }),
      },
    })

    await wrapper.get('[data-action="opening-more-cards"]').trigger("click")
    await flushPromises()
    expect(apiMock.assistant.guidedFlowAdvance).toHaveBeenLastCalledWith("run-1", {
      novel_id: "p1",
      choice: { step_id: "choose_direction", action: "more_cards" },
    })
  })

  it("骨架确认停点：给出去处与采用；采用后完成停点给三个去向", async () => {
    const adoptView = cardView({
      status: "waiting_approval",
      stop: {
        step_id: "adopt_skeleton",
        kind: "author_confirm",
        reason: "骨架已生成，待逐条取舍与采用",
        actions: [
          { action: "open_package", label: "去逐条查看与取舍" },
          { action: "adopt_skeleton", label: "采用所选条目" },
          { action: "abandon_flow", label: "结束流程" },
        ],
      },
      panel: {
        vision: "潮汐城市",
        batch: 1,
        more_allowed: false,
        cards: [],
        chosen: { title: "潮汐都市" },
        package: {
          package_suggestion_id: "pkg-9",
          knowledge_review_status: "passed",
          counts: { created_entities: 12, relations: 2 },
        },
        adopted: null,
      },
    })
    const completedView = cardView({
      status: "completed",
      stop: {
        step_id: "skeleton_ready",
        kind: "author_choice",
        reason: "世界观骨架已可用；接下来由你决定。",
        actions: [
          { action: "open_outline_suggestion", label: "生成故事总纲建议" },
          { action: "open_world_deepen", label: "继续深化世界观" },
          { action: "start_first_chapter", label: "开始写第一章" },
        ],
      },
    })
    apiMock.assistant.guidedFlowActive.mockResolvedValue(adoptView)
    apiMock.views["run-1"] = adoptView
    apiMock.assistant.guidedFlowAdvance.mockResolvedValue(completedView)

    const wrapper = await mountCard()
    expect(wrapper.text()).toContain("骨架包含：新对象 12 · 关系 2")
    await wrapper.get('[data-action="opening-open-package"]').trigger("click")
    expect(navigate).toHaveBeenCalledWith(
      "world",
      "bible",
      true,
      expect.objectContaining({ has: expect.any(Function) }),
    )
    await wrapper.get('[data-action="opening-adopt"]').trigger("click")
    await flushPromises()
    expect(apiMock.assistant.guidedFlowAdvance).toHaveBeenLastCalledWith("run-1", {
      novel_id: "p1",
      choice: { step_id: "adopt_skeleton", action: "adopt_skeleton" },
    })
    expect(wrapper.text()).toContain("生成故事总纲建议")
    await wrapper.get('[data-action="opening-first-chapter"]').trigger("click")
    expect(navigate).toHaveBeenCalledWith("outline", "story-outline", true)
    await wrapper.get('[data-action="opening-deepen"]').trigger("click")
    expect(navigate).toHaveBeenCalledWith("generate", null, true, expect.objectContaining({ has: expect.any(Function) }))
    await wrapper.get('[data-action="opening-write-first"]').trigger("click")
    expect(navigate).toHaveBeenLastCalledWith("writing")
  })
})
