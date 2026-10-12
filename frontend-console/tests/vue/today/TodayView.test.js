import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, describe, expect, it, vi } from "vitest"
import TodayView from "../../../vue/views/today/TodayView.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

function mountToday(progress, overrides = {}) {
  const navigate = vi.fn(() => true)
  setBridgeOverrides({
    router: { navigate, refresh: vi.fn(() => true) },
    api: {
      assistant: {
        guidedFlowStart: overrides.guidedFlowStart || vi.fn(async () => ({ run_id: "run-1", chapter_index: 2 })),
      },
    },
    toast: overrides.toast || vi.fn(),
    confirmAction: vi.fn((message, action) => action?.()),
  })
  const wrapper = mount(TodayView, {
    props: {
      summary: {
        project_id: "p1",
        continuation: overrides.continuation === undefined
          ? { chapter_index: 2, title: "第 2 章", has_unpublished_changes: false }
          : overrides.continuation,
      },
      creationProgress: progress,
      guidedFlowAvailable: overrides.guidedFlowAvailable !== false,
    },
  })
  return { wrapper, navigate }
}

afterEach(() => resetBridgeOverrides())

describe("TodayView 进行中的创作（BR-1b）", () => {
  it("引导流程可用时显示「引导续写」入口，点击开始流程并带 run id 进入写作页", async () => {
    const guidedFlowStart = vi.fn(async () => ({ run_id: "run-9", chapter_index: 2 }))
    const { wrapper, navigate } = mountToday([], { guidedFlowStart })
    const entry = wrapper.get('[data-action="start-guided-flow"]')
    expect(entry.text()).toContain("第 2 章")
    await entry.trigger("click")
    await flushPromises()

    expect(guidedFlowStart).toHaveBeenCalledWith({
      novel_id: "p1",
      flow_id: "continue_writing",
      chapter_index: 2,
    })
    expect(navigate).toHaveBeenCalledTimes(1)
    const [, , , query] = navigate.mock.calls[0]
    expect(query.get("flow")).toBe("run-9")
    expect(query.get("chapter_index")).toBe("2")
  })

  it("引导流程未开启时不显示入口；开始失败给出可执行提示", async () => {
    const { wrapper, navigate } = mountToday([], { guidedFlowAvailable: false })
    expect(wrapper.find('[data-action="start-guided-flow"]').exists()).toBe(false)

    const toast = vi.fn()
    const guidedFlowStart = vi.fn(async () => { throw new Error("引导流程尚未开启") })
    const failed = mountToday([], { guidedFlowStart, toast })
    await failed.wrapper.get('[data-action="start-guided-flow"]').trigger("click")
    await flushPromises()

    expect(navigate).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("引导流程尚未开启", "warning")
  })

  it("没有可继续章节时不显示引导入口", () => {
    const { wrapper } = mountToday([], { continuation: null })
    expect(wrapper.find('[data-action="start-guided-flow"]').exists()).toBe(false)
  })

  it("空项目显示新书开篇引导卡：写构想即可开始，不暴露内部标识", async () => {
    const guidedFlowStart = vi.fn(async () => ({
      run_id: "run-open-1", flow_id: "new_book_opening", status: "running", stop: null,
      steps: [], panel: { cards: [] }, settings: {},
    }))
    const { wrapper } = mountToday([], {
      continuation: null,
      guidedFlowStart,
    })
    const card = wrapper.get(".opening-flow")
    expect(card.text()).toContain("从一句构想开始新书")
    expect(card.text()).not.toContain("new_book_opening")
    await card.get('[data-action="opening-vision"]').setValue("潮汐城市")
    await card.get('[data-action="opening-start"]').trigger("click")
    await flushPromises()
    expect(guidedFlowStart).toHaveBeenCalledWith({
      novel_id: "p1",
      flow_id: "new_book_opening",
      input: { vision: "潮汐城市" },
    })
  })

  it("空项目但引导流程未开启时不显示新书开篇卡", () => {
    const { wrapper } = mountToday([], { continuation: null, guidedFlowAvailable: false })
    expect(wrapper.find(".opening-flow").exists()).toBe(false)
  })

  it("任务进行中、可审阅、已采用三种状态分开显示", () => {
    const { wrapper } = mountToday([
      { key: "task:t1", kind: "task", title: "第 2 章 · 生成正文", execution_status: "running", stop_reason: "正在处理", actions: ["view_task"] },
      { key: "candidate:c1", kind: "candidate", title: "第 2 章 · AI 正文建议", review_status: "passed", stop_reason: "可审阅，待作者采用", draft_id: "c1", chapter_index: 2 },
      { key: "adopted:d1", kind: "adopted", title: "第 1 章 · 雾港来信", adoption_status: "adopted", draft_id: "d1", chapter_index: 1 },
      { key: "adopted:d2", kind: "adopted", title: "第 3 章 · 潮声", adoption_status: "published", chapter_index: 3 },
    ])

    expect(wrapper.find("#today-progress-title").exists()).toBe(true)
    const items = wrapper.findAll(".today-workflow-list article")
    expect(items).toHaveLength(4)
    expect(items[0].classes()).toContain("is-running")
    expect(items[0].text()).toContain("正在处理")
    expect(items[1].classes()).toContain("is-review")
    expect(items[1].text()).toContain("可审阅，待作者采用")
    expect(items[2].classes()).toContain("is-adopted")
    expect(items[2].text()).toContain("已采用，可继续写作或发布")
    expect(items[3].classes()).toContain("is-published")
    expect(items[3].text()).toContain("已发布")
  })

  it("复核未通过显示警告态而非可审阅", () => {
    const { wrapper } = mountToday([
      { key: "candidate:c2", kind: "candidate", title: "第 4 章 · AI 正文建议", review_status: "unverifiable", stop_reason: "资料复核未完成，暂不能采用" },
    ])
    const card = wrapper.get(".today-workflow-list article")
    expect(card.classes()).toContain("is-warning")
    expect(card.text()).toContain("检查未完成，暂不能采用")
    expect(card.text()).not.toContain("可审阅，待采用")
  })

  it("来源过期显示需要重新确认", () => {
    const { wrapper } = mountToday([
      { key: "adopted:d3", kind: "adopted", title: "第 5 章 · 旧稿", adoption_status: "adopted", source_freshness: "stale" },
    ])
    const card = wrapper.get(".today-workflow-list article")
    expect(card.classes()).toContain("is-warning")
    expect(card.text()).toContain("依据已变化，需要重新确认")
  })

  it("候选动作深链到写作页对应章节与草稿", async () => {
    const { wrapper, navigate } = mountToday([
      { key: "candidate:c1", kind: "candidate", title: "第 2 章 · AI 正文建议", review_status: "passed", draft_id: "c1", chapter_index: 2 },
    ])
    await wrapper.get(".today-workflow-list article button").trigger("click")
    await flushPromises()

    expect(navigate).toHaveBeenCalledTimes(1)
    const [, , , query] = navigate.mock.calls[0]
    expect(query.get("chapter_index")).toBe("2")
    expect(query.get("draft_id")).toBe("c1")
  })
})
