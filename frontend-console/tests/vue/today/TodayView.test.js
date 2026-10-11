import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, describe, expect, it, vi } from "vitest"
import TodayView from "../../../vue/views/today/TodayView.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

function mountToday(progress) {
  const navigate = vi.fn(() => true)
  setBridgeOverrides({
    router: { navigate, refresh: vi.fn(() => true) },
    api: {},
    toast: vi.fn(),
    confirmAction: vi.fn((message, action) => action?.()),
  })
  const wrapper = mount(TodayView, {
    props: {
      summary: { project_id: "p1" },
      creationProgress: progress,
    },
  })
  return { wrapper, navigate }
}

afterEach(() => resetBridgeOverrides())

describe("TodayView 进行中的创作（BR-1b）", () => {
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
