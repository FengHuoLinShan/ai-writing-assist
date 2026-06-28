import { describe, it, expect } from "vitest"
import { renderFixedProgress, renderInlineProgress, renderWorkflowCard } from "../shared/progressRenderer.js"

describe("progressRenderer", () => {
  it("escapes dynamic progress text", () => {
    const html = renderInlineProgress({
      label: "<img src=x onerror=alert(1)>",
      message: "<script>alert(1)</script>",
      statusLabel: "运行中",
      status: "running",
      percent: 20,
      hasPercent: true,
      warnings: ["<b>warning</b>"],
      errorMessage: "<svg onload=alert(1)>",
    })

    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;")
    expect(html).toContain("&lt;b&gt;warning&lt;/b&gt;")
    expect(html).not.toContain("<script>")
    expect(html).not.toContain("<img")
    expect(html).not.toContain("<svg")
  })

  it("renders indeterminate progress without aria percentage", () => {
    const html = renderWorkflowCard({
      label: "补抽世界对象",
      message: "正在抽取世界对象",
      statusLabel: "运行中",
      status: "running",
      indeterminate: true,
      hasPercent: false,
      taskId: "t1",
    })

    expect(html).toContain("workflow-progress--indeterminate")
    expect(html).toContain("workflow-progress__fill--indeterminate")
    expect(html).toContain("任务 t1")
  })

  it("renders fixed progress wrapper with offset", () => {
    const html = renderFixedProgress({
      label: "发布正文",
      message: "正在创建历史状态",
      statusLabel: "运行中",
      status: "running",
      percent: 75,
      hasPercent: true,
    }, { offset: 40 })

    expect(html).toContain("workflow-progress-fixed")
    expect(html).toContain("bottom:40px")
    expect(html).toContain('aria-valuenow="75"')
  })
})
