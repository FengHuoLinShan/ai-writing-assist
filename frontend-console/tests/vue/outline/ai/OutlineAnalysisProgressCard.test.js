import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import { resetBridgeOverrides } from "../../../../vue/bridge/index.js"
import OutlineAnalysisProgressCard from "../../../../vue/views/outline/ai/OutlineAnalysisProgressCard.vue"
import { outlineAnalysisManager } from "../../../../vue/views/outline/ai/outlineWorkflowManagers.js"

function setProgress(overrides = {}) {
  outlineAnalysisManager.state.taskId = "analysis-task"
  outlineAnalysisManager.state.meta = { start_chapter: 2, end_chapter: 6 }
  outlineAnalysisManager.state.result = null
  outlineAnalysisManager.state.progress = {
    taskId: "analysis-task",
    statusLabel: "分析中",
    percent: 35,
    hasPercent: true,
    terminal: false,
    failed: false,
    done: false,
    cancelled: false,
    availableActions: ["cancel"],
    ...overrides,
  }
}

beforeEach(() => {
  outlineAnalysisManager.stop()
  outlineAnalysisManager.state.taskId = null
  outlineAnalysisManager.state.meta = null
  outlineAnalysisManager.state.progress = null
  outlineAnalysisManager.state.result = null
})

afterEach(() => resetBridgeOverrides())

describe("OutlineAnalysisProgressCard", () => {
  it("在进度卡内显示范围和当前可用操作", () => {
    setProgress()
    const wrapper = mount(OutlineAnalysisProgressCard)
    const card = wrapper.get(".workflow-progress")

    expect(card.text()).toContain("范围：第 2–6 章")
    expect(card.get('[data-action="cancel-outline-analysis"]').element.closest(".workflow-progress")).toBe(card.element)
  })

  it("终态只在卡内显示关闭任务", () => {
    setProgress({ terminal: true, failed: true, availableActions: [] })
    const wrapper = mount(OutlineAnalysisProgressCard)
    const card = wrapper.get(".workflow-progress")

    expect(card.find('[data-action="cancel-outline-analysis"]').exists()).toBe(false)
    expect(card.get('[data-action="dismiss-outline-analysis"]').element.closest(".workflow-progress")).toBe(card.element)
  })
})
