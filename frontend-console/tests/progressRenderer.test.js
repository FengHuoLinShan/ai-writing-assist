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

  it("renders phase artifact summaries", () => {
    const html = renderWorkflowCard({
      label: "场景自动提取",
      message: "已完成",
      statusLabel: "已完成",
      status: "done",
      done: true,
      hasPercent: true,
      percent: 100,
      phaseArtifacts: {
        scene_commit: {
          status: "completed",
          counts: { total_scenes: 60 },
          coverage: { missing_chapters: [] },
          repair: { attempts: 1 },
        },
      },
    })

    expect(html).toContain("scene_commit")
    expect(html).toContain("Scene 60")
    expect(html).toContain("修复 1")
  })

  it("renders detailed progress collapsed by default and escaped", () => {
    const html = renderWorkflowCard({
      label: "深度导入",
      message: "处理中",
      statusLabel: "运行中",
      status: "running",
      hasPercent: false,
      indeterminate: true,
      phaseTimeline: [{ phase: "phase0_prefetch", status: "completed", duration_s: 1.2 }],
      progressEvents: [
        {
          event: "phase_finished",
          phase: "<script>",
          status: "completed",
          message: "<img src=x>",
          details: { raw: "<b>safe</b>" },
        },
      ],
      acceptanceChecks: [
        { name: "coverage", phase: "phase0_prefetch", ok: false, message: "缺章" },
      ],
      phaseErrors: [{ phase: "phase0_prefetch", error_kind: "missing", message: "<svg>" }],
      diagnosticCounts: { scene_count: 2 },
    })

    expect(html).toContain("<details class=\"workflow-progress__details\">")
    expect(html).toContain("详细进度")
    expect(html).toContain("阶段时间线")
    expect(html).toContain("门禁检查")
    expect(html).toContain("&lt;img src=x&gt;")
    expect(html).not.toContain("<script>")
    expect(html).not.toContain("<svg>")
  })

  it("opens detailed progress when requested", () => {
    const html = renderWorkflowCard({
      label: "深度导入",
      message: "处理中",
      statusLabel: "运行中",
      status: "running",
      progressEvents: [{ event: "phase_started", phase: "phase0_prefetch" }],
    }, { detailLevel: "detailed" })

    expect(html).toContain("<details class=\"workflow-progress__details\" open>")
  })

  it("preserves detailed progress open state across rerenders", () => {
    sessionStorage.setItem("workflow-progress-details:t-sticky", "open")

    const html = renderWorkflowCard({
      taskId: "t-sticky",
      label: "场景自动提取",
      message: "处理中",
      statusLabel: "运行中",
      status: "running",
      progressEvents: [{ event: "phase_started", phase: "phase1a_scene_slicing" }],
    })

    expect(html).toContain('data-details-storage-key="workflow-progress-details:t-sticky"')
    expect(html).toContain("<details class=\"workflow-progress__details\" data-details-storage-key=\"workflow-progress-details:t-sticky\" open>")

    sessionStorage.removeItem("workflow-progress-details:t-sticky")
  })
})
