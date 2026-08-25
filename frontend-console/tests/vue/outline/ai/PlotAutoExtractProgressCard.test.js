/**
 * PlotAutoExtractProgressCard 组件测试 — DOM 对齐 vanilla _renderPlotAutoExtractProgress。
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { mount } from "@vue/test-utils"
import PlotAutoExtractProgressCard from "../../../../vue/views/outline/ai/PlotAutoExtractProgressCard.vue"
import { plotAutoExtractManager } from "../../../../vue/views/outline/ai/outlineWorkflowManagers.js"
import { resetBridgeOverrides } from "../../../../vue/bridge/index.js"

beforeEach(() => {
  plotAutoExtractManager.stop()
  plotAutoExtractManager.state.taskId = null
  plotAutoExtractManager.state.status = "就绪"
  plotAutoExtractManager.state.meta = null
  plotAutoExtractManager.state.progress = null
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("渲染契约", () => {
  it("无 progress 时渲染空字符串", () => {
    expect(plotAutoExtractManager.state.progress).toBeNull()
    const wrapper = mount(PlotAutoExtractProgressCard)
    // v-if 渲染为注释节点，不作为实际 DOM 输出
    expect(wrapper.find(".outline-progress-card-wrap").exists()).toBe(false)
  })

  it("有 progress 时渲染 progress card wrap", () => {
    plotAutoExtractManager.state.taskId = "task-plot"
    plotAutoExtractManager.state.status = "运行中"
    plotAutoExtractManager.state.meta = { start_chapter: 3, end_chapter: 7, label: "剧情线自动提取" }
    plotAutoExtractManager.state.progress = {
      taskId: "task-plot",
      label: "剧情线自动提取",
      statusLabel: "运行中",
      message: "正在提取",
      percent: 60,
      hasPercent: true,
      failed: false,
      done: false,
      cancelled: false,
      indeterminate: false,
      terminal: false,
    }
    const wrapper = mount(PlotAutoExtractProgressCard)
    expect(wrapper.find(".outline-progress-card-wrap").exists()).toBe(true)
    expect(wrapper.findComponent({ name: "WorkflowProgressCard" }).exists()).toBe(true)
    expect(wrapper.get(".workflow-progress__destination").text()).toBe("范围：第 3–7 章")
  })

  it("meta 中的章节范围文本", () => {
    plotAutoExtractManager.state.taskId = "task-plot2"
    plotAutoExtractManager.state.status = "运行中"
    plotAutoExtractManager.state.meta = { start_chapter: 1, end_chapter: 5, label: "剧情线自动提取" }
    plotAutoExtractManager.state.progress = {
      taskId: "task-plot2",
      label: "剧情线自动提取",
      statusLabel: "运行中",
      message: "",
    }
    const wrapper = mount(PlotAutoExtractProgressCard)
    expect(wrapper.text()).toContain("剧情线自动提取")
    expect(wrapper.text()).toContain("范围：第 1–5 章")
  })
})
