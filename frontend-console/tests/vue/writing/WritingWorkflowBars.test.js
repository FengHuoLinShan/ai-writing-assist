import { mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it } from "vitest"
import WorkflowProgressCard from "../../../vue/components/WorkflowProgressCard.vue"
import WritingWorkflowBars from "../../../vue/views/writing/components/WritingWorkflowBars.vue"

describe("WritingWorkflowBars", () => {
  beforeEach(() => sessionStorage.clear())

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

  it("展示实时位置与质量统计，并暴露审计和地图重试入口", async () => {
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
          qualityStats: { schema_422_rate: "2%", phase3: { error_kind: "schema_failure" } },
          phaseArtifacts: { phase1: { count: 2, error_kind: "provider_error" } },
          acceptanceChecks: [{ name: "coverage" }],
          diagnosticCounts: { warnings: 1 },
          throttleReasons: ["budget"],
          mapNextStepError: "网络错误",
        } },
      },
    })
    expect(wrapper.text()).toContain("世界对象与关系提取")
    expect(wrapper.text()).toContain("schema_422_rate：2%")
    expect(wrapper.text()).not.toContain("error_kind")
    expect(wrapper.text()).not.toContain("schema_failure")
    expect(wrapper.text()).not.toContain("provider_error")
    expect(wrapper.text()).toContain("结果格式未通过校验")
    expect(wrapper.text()).toContain("地图下一步暂时无法加载")
    await wrapper.findAll("button").find((button) => button.text() === "重试").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "查看快照状态").trigger("click")
    expect(wrapper.emitted("retry-map")).toHaveLength(1)
    expect(wrapper.emitted("open-audit")).toHaveLength(1)
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

  it("完成态保留地图下一步操作", async () => {
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: null },
        conflict: { latest: null, error: null },
        deepImport: {
          taskId: "map-task",
          progress: {
            status: "done",
            percent: 100,
            mapNextStep: { action: "review-locations", count: 3 },
          },
        },
      },
    })
    const button = wrapper.findAll("button").find((item) => item.text() === "先审核 3 个地点")
    expect(button).toBeTruthy()
    await button.trigger("click")
    expect(wrapper.emitted("map-next")).toHaveLength(1)
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
    expect(wrapper.text()).toContain("Phase 1b · Scene 字段补全")
  })

  it("允许宿主把最近冲突检查移到顶部操作行", () => {
    const wrapper = mount(WritingWorkflowBars, {
      props: {
        publish: { active: false, phase: null },
        conflict: { latest: { id: "check-1", status: "completed" }, error: null },
        deepImport: { taskId: null, progress: null },
        showConflict: false,
      },
    })
    expect(wrapper.find("#writing-conflict-strip").exists()).toBe(false)
  })
})
