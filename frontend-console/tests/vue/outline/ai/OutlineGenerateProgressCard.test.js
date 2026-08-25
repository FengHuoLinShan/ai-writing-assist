/**
 * OutlineGenerateProgressCard 组件测试 — DOM 对齐 vanilla _renderOutlineGenerateProgress。
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { mount } from "@vue/test-utils"
import OutlineGenerateProgressCard from "../../../../vue/views/outline/ai/OutlineGenerateProgressCard.vue"
import { outlineGenerateManager } from "../../../../vue/views/outline/ai/outlineWorkflowManagers.js"
import { resetBridgeOverrides } from "../../../../vue/bridge/index.js"

beforeEach(() => {
  outlineGenerateManager.stop()
  outlineGenerateManager.state.taskId = null
  outlineGenerateManager.state.status = "就绪"
  outlineGenerateManager.state.meta = null
  outlineGenerateManager.state.progress = null
  outlineGenerateManager.state.preview = null
})

afterEach(() => {
  resetBridgeOverrides()
})

function setProgress(overrides = {}) {
  outlineGenerateManager.state.taskId = overrides.taskId || "task-gen"
  outlineGenerateManager.state.status = "运行中"
  outlineGenerateManager.state.meta = overrides.meta || { target: "plot_thread", mode: "create", label: "剧情线" }
  outlineGenerateManager.state.progress = {
    taskId: overrides.taskId || "task-gen",
    label: overrides.label || "剧情线建议",
    statusLabel: overrides.statusLabel || "运行中",
    message: overrides.message || "正在生成",
    percent: overrides.percent ?? 45,
    hasPercent: overrides.hasPercent ?? true,
    failed: overrides.failed ?? false,
    done: overrides.done ?? false,
    cancelled: overrides.cancelled ?? false,
    indeterminate: overrides.indeterminate ?? false,
    terminal: overrides.terminal ?? false,
  }
}

describe("渲染契约", () => {
  it("无 progress 时渲染空字符串", () => {
    expect(outlineGenerateManager.state.progress).toBeNull()
    const wrapper = mount(OutlineGenerateProgressCard)
    // v-if 渲染为注释节点，不作为实际 DOM 输出
    expect(wrapper.find(".outline-progress-card-wrap").exists()).toBe(false)
  })

  it("有 progress 时渲染 progress card wrap", () => {
    setProgress()
    const wrapper = mount(OutlineGenerateProgressCard)
    expect(wrapper.find(".outline-progress-card-wrap").exists()).toBe(true)
    expect(wrapper.findComponent({ name: "WorkflowProgressCard" }).exists()).toBe(true)
    expect(wrapper.get(".workflow-progress__destination").text()).toBe("新增设计")
  })

  it("有 preview 时渲染预览就绪区与按钮", () => {
    setProgress()
    outlineGenerateManager.state.preview = {
      sourceTaskId: "st1",
      contextConfirmationId: "cc1",
      draftStructure: {},
    }
    const wrapper = mount(OutlineGenerateProgressCard)
    expect(wrapper.find(".outline-preview-ready").exists()).toBe(true)
    const btn = wrapper.find('[data-action="view-outline-generate-preview"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toBe("检查建议")
    expect(btn.element.closest(".workflow-progress")).not.toBeNull()
  })

  it("无 preview 时隐藏预览就绪区", () => {
    setProgress()
    outlineGenerateManager.state.preview = null
    const wrapper = mount(OutlineGenerateProgressCard)
    expect(wrapper.find(".outline-preview-ready").exists()).toBe(false)
  })
})

describe("title / range 文本", () => {
  it("显示 meta.label + 建议", () => {
    setProgress({ meta: { target: "plot_thread", mode: "create", label: "剧情线" } })
    const wrapper = mount(OutlineGenerateProgressCard)
    // WorkflowProgressCard 渲染 title
    expect(wrapper.text()).toContain("剧情线")
  })

  it("无 meta 时回落默认文本", () => {
    outlineGenerateManager.state.meta = null
    outlineGenerateManager.state.taskId = "t1"
    outlineGenerateManager.state.status = "运行中"
    outlineGenerateManager.state.progress = {
      taskId: "t1",
      label: "当前层建议",
      statusLabel: "运行中",
      message: "",
    }
    const wrapper = mount(OutlineGenerateProgressCard)
    expect(wrapper.text()).toContain("当前层")
  })
})
