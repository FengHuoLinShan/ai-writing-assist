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
          qualityStats: { schema_422_rate: "2%" },
          phaseArtifacts: { phase1: { count: 2 } },
          acceptanceChecks: [{ name: "coverage" }],
          diagnosticCounts: { warnings: 1 },
          throttleReasons: ["budget"],
          mapNextStepError: "网络错误",
        } },
      },
    })
    expect(wrapper.text()).toContain("entity_extraction")
    expect(wrapper.text()).toContain("schema_422_rate：2%")
    expect(wrapper.text()).toContain("地图下一步暂时无法加载")
    await wrapper.findAll("button").find((button) => button.text() === "重试").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "查看快照状态").trigger("click")
    expect(wrapper.emitted("retry-map")).toHaveLength(1)
    expect(wrapper.emitted("open-audit")).toHaveLength(1)
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
})
