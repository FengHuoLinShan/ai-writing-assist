import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import WritingFlowHost from "../../../vue/views/writing/components/WritingFlowHost.vue"

function makeController(view, overrides = {}) {
  return {
    state: { view, busy: false, visible: Boolean(view), error: null },
    confirmReference: overrides.confirmReference || vi.fn(),
    abandonFlow: overrides.abandonFlow || vi.fn(async () => null),
    saveSettings: overrides.saveSettings || vi.fn(async () => null),
    openCandidate: overrides.openCandidate || vi.fn(),
    dismiss: overrides.dismiss || vi.fn(),
  }
}

function mountHost(controller) {
  return mount(WritingFlowHost, { props: { controller } })
}

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

  it("流程设置只在确认停点出现，切换即保存", async () => {
    const saveSettings = vi.fn(async () => null)
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
      settings: { semantic_review: true },
    }, { saveSettings })
    const wrapper = mountHost(controller)
    const toggle = wrapper.get('[data-action="flow-toggle-semantic-review"]')
    expect(toggle.element.checked).toBe(true)
    toggle.element.checked = false
    await toggle.trigger("change")
    expect(saveSettings).toHaveBeenCalledWith(false)
  })
})
