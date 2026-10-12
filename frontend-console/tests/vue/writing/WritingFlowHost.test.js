import { afterEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import WritingFlowHost from "../../../vue/views/writing/components/WritingFlowHost.vue"

const navigate = vi.fn()

function makeController(view, overrides = {}) {
  return {
    state: { view, busy: false, visible: Boolean(view), error: null },
    confirmReference: overrides.confirmReference || vi.fn(),
    abandonFlow: overrides.abandonFlow || vi.fn(async () => null),
    saveSettings: overrides.saveSettings || vi.fn(async () => null),
    openCandidate: overrides.openCandidate || vi.fn(),
    choose: overrides.choose || vi.fn(async () => null),
    dismiss: overrides.dismiss || vi.fn(),
  }
}

function mountHost(controller) {
  setBridgeOverrides({ router: { navigate, refresh: vi.fn(() => true) } })
  return mount(WritingFlowHost, { props: { controller } })
}

afterEach(() => {
  navigate.mockClear()
  resetBridgeOverrides()
})

describe("WritingFlowHost（引导流程伙伴区）", () => {
  it("无流程时不渲染任何宿主 DOM", () => {
    const wrapper = mountHost(makeController(null))
    expect(wrapper.find(".writing-flow-host").exists()).toBe(false)
  })

  it("确认停点：说明为什么停、给主操作，且不暴露内部标识", () => {
    const controller = makeController({
      run_id: "run-1",
      flow_id: "continue_writing",
      title: "继续写下一场",
      status: "waiting_approval",
      chapter_index: 3,
      stop: {
        step_id: "confirm_reference",
        kind: "author_confirm",
        reason: "需要你确认本章资料后才能生成；可在本页就地核对或修改本章目标。",
        actions: [{ action: "confirm_reference", label: "确认本章资料" }],
      },
      steps: [
        { step_id: "confirm_reference", title: "确认本章资料", state: "active", detail: "" },
        { step_id: "generate_candidate", title: "生成正文候选", state: "pending", detail: "" },
      ],
      settings: { semantic_review: true },
    })
    const wrapper = mountHost(controller)
    expect(wrapper.text()).toContain("继续写下一场")
    expect(wrapper.text()).toContain("等你的决定")
    expect(wrapper.text()).toContain("需要你确认本章资料后才能生成")
    expect(wrapper.text()).not.toContain("continue_writing")
    expect(wrapper.text()).not.toContain("confirm_reference")
    const primary = wrapper.get('[data-action="flow-confirm_reference"]')
    expect(primary.classes()).toContain("btn-primary")
  })

  it("主操作按停点动作分派", async () => {
    const confirmReference = vi.fn()
    const controller = makeController({
      run_id: "run-1",
      title: "继续写下一场",
      status: "waiting_approval",
      stop: {
        step_id: "confirm_reference",
        kind: "author_confirm",
        reason: "r",
        actions: [{ action: "confirm_reference", label: "确认本章资料" }],
      },
      steps: [],
      settings: {},
    }, { confirmReference })
    const wrapper = mountHost(controller)
    await wrapper.get('[data-action="flow-confirm_reference"]').trigger("click")
    expect(confirmReference).toHaveBeenCalledTimes(1)
  })

  it("可审阅停点提供查看候选与结束流程；open_writing 不在写作页展示", () => {
    const openCandidate = vi.fn()
    const controller = makeController({
      run_id: "run-1",
      title: "继续写下一场",
      status: "waiting_approval",
      candidate: { draft_id: "c1", chapter_index: 3 },
      stop: {
        step_id: "review_candidate",
        kind: "author_choice",
        reason: "可审阅，待作者采用",
        actions: [
          { action: "open_candidate", label: "查看候选" },
          { action: "abandon_flow", label: "结束流程" },
        ],
      },
      steps: [],
      settings: {},
    }, { openCandidate })
    const wrapper = mountHost(controller)
    expect(wrapper.find('[data-action="flow-open_writing"]').exists()).toBe(false)
    wrapper.get('[data-action="flow-open_candidate"]').trigger("click")
    expect(openCandidate).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-action="flow-abandon_flow"]').exists()).toBe(true)
  })

  it("流程设置只在确认停点出现，切换即保存（含滚动窗口默认值）", async () => {
    const saveSettings = vi.fn(async () => null)
    const controller = makeController({
      run_id: "run-1",
      flow_id: "continue_writing",
      title: "继续写下一场",
      status: "waiting_approval",
      stop: {
        step_id: "confirm_reference",
        kind: "author_confirm",
        reason: "r",
        actions: [{ action: "confirm_reference", label: "确认本章资料" }],
      },
      steps: [],
      settings: { semantic_review: true, planning_window: 3 },
    }, { saveSettings })
    const wrapper = mountHost(controller)
    const toggle = wrapper.get('[data-action="flow-toggle-semantic-review"]')
    expect(toggle.element.checked).toBe(true)
    toggle.element.checked = false
    await toggle.trigger("change")
    expect(saveSettings).toHaveBeenCalledWith(false, 3)
    // 规划窗口可调（1-5 章，默认 3）；调整时沿用当前审查开关。
    const select = wrapper.get('[data-action="flow-planning-window"]')
    expect(select.element.value).toBe("3")
    select.element.value = "5"
    await select.trigger("change")
    expect(saveSettings).toHaveBeenLastCalledWith(true, 5)
  })

  it("采用后的滚动规划停点：说明窗口与补足建议，可打开结构工作台或完成流程", async () => {
    const choose = vi.fn(async () => null)
    const controller = makeController({
      run_id: "run-1",
      flow_id: "continue_writing",
      title: "继续写下一场",
      status: "waiting_approval",
      chapter_index: 1,
      stop: {
        step_id: "rolling_offer",
        kind: "author_choice",
        reason: "第 1 章已采用。接下来的第 2 至 4 章可以生成剧情线与篇章候选；后方已规划 0 章，不足 2 章。",
        actions: [
          { action: "plan_ahead", label: "规划接下来几章" },
          { action: "decline", label: "先不用" },
          { action: "abandon_flow", label: "结束流程" },
        ],
      },
      steps: [],
      settings: {},
      panel: { rolling: { window: { start: 2, end: 4 }, planned_chapters: 0 } },
    }, { choose })
    const wrapper = mountHost(controller)
    expect(wrapper.text()).toContain("不足 2 章")
    await wrapper.get('[data-action="flow-plan_ahead"]').trigger("click")
    expect(choose).toHaveBeenCalledWith("rolling_offer", { action: "plan_ahead" })

    const reviewer = makeController({
      run_id: "run-2",
      flow_id: "continue_writing",
      title: "继续写下一场",
      status: "waiting_approval",
      stop: {
        step_id: "rolling_review",
        kind: "author_choice",
        reason: "第 2 至 4 章的剧情线与篇章候选已生成。",
        actions: [
          { action: "open_outline", label: "打开结构工作台" },
          { action: "finish_flow", label: "完成流程" },
          { action: "abandon_flow", label: "结束流程" },
        ],
      },
      steps: [],
      settings: {},
    }, { choose })
    const wrapper2 = mountHost(reviewer)
    await wrapper2.get('[data-action="flow-open_outline"]').trigger("click")
    expect(navigate).toHaveBeenCalled()
    await wrapper2.get('[data-action="flow-finish_flow"]').trigger("click")
    expect(choose).toHaveBeenCalledWith("rolling_review", { action: "finish_flow" })
  })
})
