import { mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import WorkflowProgressCard from "../../../vue/components/WorkflowProgressCard.vue"
import WritingWorkflowBars from "../../../vue/views/writing/components/WritingWorkflowBars.vue"

describe("WritingWorkflowBars", () => {
  beforeEach(() => sessionStorage.clear())
  afterEach(() => vi.useRealTimers())

  it("顶部浮层中无后续操作的成功态在 3 秒后关闭", async () => {
    vi.useFakeTimers()
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: "done", message: "已设为正式正文", retryable: false },
        conflict: { latest: null, error: null },
        deepImport: { taskId: null, progress: null },
      },
    })

    expect(wrapper.get(".writing-workflow-notices").attributes("aria-label")).toBe("写作任务通知")
    await vi.advanceTimersByTimeAsync(2999)
    expect(wrapper.emitted("dismiss-publish")).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(wrapper.emitted("dismiss-publish")).toHaveLength(1)
  })

  it("失败、取消、降级和带业务操作的成功态持续显示", async () => {
    vi.useFakeTimers()
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: "failed", message: "失败", retryable: true },
        conflict: { latest: null, error: null },
        generation: { taskId: "generation-1", progress: { status: "done", terminal: true }, result: { draft_id: "candidate-1" } },
        conflictTask: { taskId: "conflict-1", progress: { status: "cancelled", terminal: true } },
        deepImport: { taskId: "deep-1", progress: { status: "done", degraded: true, availableActions: [] } },
      },
    })

    await vi.advanceTimersByTimeAsync(5000)
    expect(wrapper.emitted("dismiss-publish")).toBeUndefined()
    expect(wrapper.emitted("dismiss-generation")).toBeUndefined()
    expect(wrapper.emitted("dismiss-conflict-task")).toBeUndefined()
    expect(wrapper.emitted("dismiss")).toBeUndefined()
  })

  it("任务更新会清理旧计时器，只关闭新完成态", async () => {
    vi.useFakeTimers()
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: null },
        conflict: { latest: null, error: null },
        conflictTask: { taskId: "conflict-1", progress: { status: "done", terminal: true } },
        deepImport: { taskId: null, progress: null },
      },
    })

    await vi.advanceTimersByTimeAsync(2000)
    await wrapper.setProps({ conflictTask: { taskId: "conflict-2", progress: { status: "running", terminal: false } } })
    await vi.advanceTimersByTimeAsync(2000)
    expect(wrapper.emitted("dismiss-conflict-task")).toBeUndefined()
    await wrapper.setProps({ conflictTask: { taskId: "conflict-2", progress: { status: "done", terminal: true } } })
    await vi.advanceTimersByTimeAsync(3000)
    expect(wrapper.emitted("dismiss-conflict-task")).toHaveLength(1)
  })

  it("卸载时清理自动关闭计时器", async () => {
    vi.useFakeTimers()
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: "done", message: "完成", retryable: false },
        conflict: { latest: null, error: null },
        deepImport: { taskId: null, progress: null },
      },
    })
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(3000)
    expect(wrapper.emitted("dismiss-publish")).toBeUndefined()
  })

  it("运行态复用共享紧凑任务卡，显示准确百分比并持久化折叠选择", async () => {
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: null },
        conflict: { latest: null, error: null },
        deepImport: {
          taskId: "deep-task-1",
          progress: {
            label: "深度导入",
            message: "正在提取世界对象",
            status: "running",
            percent: 1,
            availableActions: ["cancel"],
          },
        },
      },
    })

    expect(wrapper.findComponent(WorkflowProgressCard).exists()).toBe(true)
    const card = wrapper.get("details.workflow-progress")
    expect(card.attributes("open")).toBeUndefined()
    expect(card.attributes("data-collapse-storage-key")).toBe("workflow-progress-card:deep-task-1")
    expect(wrapper.get("summary.workflow-progress__compact").text()).toContain("深度导入")
    expect(wrapper.get(".workflow-progress__meta").text()).toContain("1%")
    expect(wrapper.get('[role="progressbar"]').attributes("aria-valuenow")).toBe("1")
    expect(wrapper.text()).not.toContain("任务 deep-task-1")

    card.element.open = true
    await card.trigger("toggle")
    expect(sessionStorage.getItem("workflow-progress-card:deep-task-1")).toBe("open")
  })

  it("渲染恢复操作和经过转义的快照摘要", async () => {
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: null },
        conflict: { latest: null, error: null },
        deepImport: {
          taskId: "recovery-task",
          progress: {
            label: "深度导入",
            message: "<img src=x>",
            status: "failed",
            availableActions: ["resume", "abandon"],
            auditSummary: { warning: "<script>" },
          },
        },
      },
    })
    expect(wrapper.text()).toContain("<img src=x>")
    expect(wrapper.find("img").exists()).toBe(false)
    expect(wrapper.find("script").exists()).toBe(false)
    expect(wrapper.text()).toContain("继续")
    expect(wrapper.get("details.workflow-progress").attributes("open")).toBeDefined()
    await wrapper.get("button.btn-primary").trigger("click")
    expect(wrapper.emitted("resume")).toHaveLength(1)
  })

  it("用户保存的收起选择优先于恢复态自动展开", () => {
    sessionStorage.setItem("workflow-progress-card:recovery-task", "closed")
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: null },
        conflict: { latest: null, error: null },
        deepImport: {
          taskId: "recovery-task",
          progress: {
            status: "failed",
            message: "需要恢复",
            recoveryRequired: true,
            availableActions: ["resume", "abandon"],
          },
        },
      },
    })
    expect(wrapper.get("details.workflow-progress").attributes("open")).toBeUndefined()
  })

  it("只有恢复标记但没有后端 action 时不暴露继续或放弃", () => {
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: null },
        conflict: { latest: null, error: null },
        deepImport: {
          taskId: "recovery-pending",
          progress: {
            status: "failed",
            message: "正在确认恢复策略",
            recoveryRequired: true,
            availableActions: [],
          },
        },
      },
    })

    expect(wrapper.text()).toContain("后端正在确认可用的恢复操作")
    expect(wrapper.findAll("button").some((button) => button.text() === "继续")).toBe(false)
    expect(wrapper.findAll("button").some((button) => button.text() === "放弃恢复")).toBe(false)
  })

  it("剧情结构分析使用不确定进度语义，同时保留取消入口", async () => {
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: null },
        conflict: { latest: null, error: null },
        deepImport: {
          taskId: "structure-task",
          progress: {
            status: "running",
            currentPhase: "structure_analysis",
            percent: 80,
            availableActions: ["cancel"],
          },
        },
      },
    })
    expect(wrapper.find(".workflow-progress__fill--indeterminate").exists()).toBe(true)
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
    expect(wrapper.text()).toContain("正在提取剧情结构")
    await wrapper.findAll("button").find((button) => button.text() === "取消任务").trigger("click")
    expect(wrapper.emitted("cancel")).toHaveLength(1)
  })

  it("后端未返回 cancel action 时不显示取消入口", () => {
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: null },
        conflict: { latest: null, error: null },
        deepImport: {
          taskId: "pending-contract",
          progress: { status: "running", availableActions: [] },
        },
      },
    })

    expect(wrapper.findAll("button").some((button) => button.text() === "取消任务")).toBe(false)
  })

  it("展示实时位置与质量统计，并暴露审计入口", async () => {
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: null },
        conflict: { latest: null, error: null },
        deepImport: { taskId: "done-task", progress: {
          status: "done",
          message: "完成",
          currentPhase: "entity_extraction",
          currentWindow: { start: 1, end: 3 },
          currentOperation: "merge",
          qualityStatus: "partial",
          qualityStats: {
            phase1a: { fallback_count: 2 },
            phase3: {
              evidence_gate_passed_count: 5,
              evidence_gate_review_count: 4,
              error_kind: "schema_failure",
            },
          },
          assetSummary: { review: 3 },
          phaseArtifacts: { phase1: { count: 2, error_kind: "provider_error" } },
          acceptanceChecks: [{ name: "coverage" }],
          diagnosticCounts: { warnings: 1 },
          throttleReasons: ["budget"],
        } },
      },
    })
    expect(wrapper.text()).toContain("世界对象与关系提取")
    expect(wrapper.text()).toContain("证据门禁通过：5")
    expect(wrapper.text()).toContain("待复核：4")
    expect(wrapper.text()).toContain("章级降级：2")
    expect(wrapper.text()).not.toContain("error_kind")
    expect(wrapper.text()).not.toContain("schema_failure")
    expect(wrapper.text()).not.toContain("provider_error")
    expect(wrapper.text()).not.toContain("结果格式未通过校验")
    await wrapper.findAll("button").find((button) => button.text() === "查看快照状态").trigger("click")
    expect(wrapper.emitted("open-audit")).toHaveLength(1)
  })

  it("完成卡展示自动去重结果与遗留复核入口", () => {
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: null },
        conflict: { latest: null, error: null },
        deepImport: {
          taskId: "dedup-done",
          progress: {
            status: "done",
            workflowType: "deep_import",
            phase2Dedup: { auto_merged: 3, review_required: 2 },
          },
        },
      },
    })

    expect(wrapper.text()).toContain("自动归并 3 个重复对象，仍有 2 组可稍后检查")
    expect(wrapper.text()).toContain("人物与世界 → 智能去重")
  })

  it("失败消息中的内部健康码会转换为作者提示", () => {
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: null },
        conflict: { latest: null, error: null },
        deepImport: {
          taskId: "failed-health",
          progress: {
            status: "failed",
            message: "结构健康检查失败：health.error_kind=schema_failure",
            availableActions: ["dismiss"],
          },
        },
      },
    })

    expect(wrapper.text()).toContain("结构健康检查失败：原因：结果格式未通过校验")
    expect(wrapper.text()).not.toContain("error_kind")
    expect(wrapper.text()).not.toContain("schema_failure")
  })

  it("降级完成态自动展开并隐藏内部原因码", () => {
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: null },
        conflict: { latest: null, error: null },
        deepImport: {
          taskId: "degraded-task",
          progress: {
            status: "done",
            percent: 100,
            qualityStatus: "partial",
            degraded: true,
            degradedReason: "phase1b_422_rate_exceeded",
            phase1aFallback: true,
            phaseErrors: [{
              phase: "phase1b_enrichment",
              error_kind: "schema_failure",
              message: "部分 Scene 已使用可复核结果继续导入",
            }],
          },
        },
      },
    })

    expect(wrapper.get("details.workflow-progress").attributes("open")).toBeDefined()
    expect(wrapper.text()).toContain("部分降级完成")
    expect(wrapper.text()).toContain("部分步骤已降级完成，请检查需要人工处理的结果")
    expect(wrapper.text()).toContain("自动整理失败，已使用质量补强结果继续导入")
    expect(wrapper.text()).not.toContain("phase1b_422_rate_exceeded")
    expect(wrapper.text()).not.toContain("schema_failure")
    expect(wrapper.text()).not.toContain("phase1b_enrichment")
    expect(wrapper.text()).toContain("结果格式未通过校验")
    expect(wrapper.text()).toContain("阶段 3 · 补充场景资料")
  })

})
