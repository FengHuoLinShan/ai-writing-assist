/**
 * OutlineAnalysisResultCard 组件测试 — DOM 对齐 vanilla _renderOutlineAnalysisResult。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { mount } from "@vue/test-utils"
import OutlineAnalysisResultCard from "../../../../vue/views/outline/ai/OutlineAnalysisResultCard.vue"
import { outlineAnalysisManager } from "../../../../vue/views/outline/ai/outlineWorkflowManagers.js"
import { resetBridgeOverrides } from "../../../../vue/bridge/index.js"

beforeEach(() => {
  outlineAnalysisManager.stop()
  outlineAnalysisManager.state.taskId = null
  outlineAnalysisManager.state.status = "就绪"
  outlineAnalysisManager.state.meta = null
  outlineAnalysisManager.state.progress = null
  outlineAnalysisManager.state.result = null
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("渲染契约", () => {
  it("无 result 时渲染空字符串", () => {
    expect(outlineAnalysisManager.state.result).toBeFalsy()
    const wrapper = mount(OutlineAnalysisResultCard)
    // v-if 渲染为注释节点，不作为实际 DOM 输出
    expect(wrapper.find(".outline-analysis-result").exists()).toBe(false)
  })

  it("有 result 时渲染分析结果区域", () => {
    outlineAnalysisManager.state.result = {
      markdown: "## 分析结论\n结构完整。",
      contextSummary: {
        sections: [{ key: "ref1", title: "参考资料一", sources: ["主线"], sourceCount: 1 }],
        warnings: ["编译提示"],
      },
    }
    const wrapper = mount(OutlineAnalysisResultCard)
    expect(wrapper.find(".outline-analysis-result").exists()).toBe(true)
    expect(wrapper.find(".outline-analysis-markdown").text()).toContain("结构完整。")
  })

  it("有上下文详情时渲染 details 块", () => {
    outlineAnalysisManager.state.result = {
      markdown: "分析内容",
      contextSummary: {
        sections: [{ key: "ref1", title: "参考资料一", sources: ["主线", "副线"], sourceCount: 2 }],
        warnings: [],
      },
    }
    const wrapper = mount(OutlineAnalysisResultCard)
    expect(wrapper.find("details.outline-analysis-context").exists()).toBe(true)
    expect(wrapper.find("details.outline-analysis-context").text()).toContain("参考资料一")
  })

  it("无上下文详情时隐藏 details 块", () => {
    outlineAnalysisManager.state.result = {
      markdown: "分析内容",
      contextSummary: { sections: [], warnings: [] },
    }
    const wrapper = mount(OutlineAnalysisResultCard)
    expect(wrapper.find("details.outline-analysis-context").exists()).toBe(false)
  })

  it("收起结果只清理本地分析状态", async () => {
    outlineAnalysisManager.state.result = {
      markdown: "分析内容",
      contextSummary: {},
    }
    const wrapper = mount(OutlineAnalysisResultCard)
    const btn = wrapper.find('[data-action="dismiss-outline-analysis"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toBe("收起结果")
    await btn.trigger("click")
    expect(outlineAnalysisManager.state.result).toBeNull()
    expect(globalThis.router.refresh).not.toHaveBeenCalled()
  })
})
