/**
 * WorkflowProgressCard 组件测试 — DOM 契约对齐 shared/progressRenderer.js。
 */
import { describe, it, expect, beforeEach } from "vitest"
import { mount } from "@vue/test-utils"
import WorkflowProgressCard from "../../vue/components/WorkflowProgressCard.vue"

function makeProgress(overrides = {}) {
  return {
    taskId: "task-1",
    label: "索引重建",
    statusLabel: "运行中",
    message: "正在处理",
    percent: 42,
    hasPercent: true,
    failed: false,
    done: false,
    cancelled: false,
    indeterminate: false,
    ...overrides,
  }
}

beforeEach(() => {
  sessionStorage.clear()
})

describe("渲染契约", () => {
  it("折叠形态：details + summary.compact + body", () => {
    const wrapper = mount(WorkflowProgressCard, { props: { progress: makeProgress() } })
    const root = wrapper.find("details.workflow-progress")
    expect(root.exists()).toBe(true)
    expect(root.attributes("data-collapse-storage-key")).toBe("workflow-progress-card:task-1")
    expect(wrapper.find("summary.workflow-progress__compact").exists()).toBe(true)
    expect(wrapper.find(".workflow-progress__chevron").exists()).toBe(true)
    expect(wrapper.find(".workflow-progress__title").text()).toBe("索引重建")
    expect(wrapper.find(".workflow-progress__meta").text()).toContain("42%")
    expect(wrapper.find(".workflow-progress__meta").text()).toContain("任务 task-1")
    expect(wrapper.find(".workflow-progress__body").exists()).toBe(true)
  })

  it("非折叠形态：div.workflow-progress--expanded 且无 chevron", () => {
    const wrapper = mount(WorkflowProgressCard, {
      props: { progress: makeProgress(), collapsible: false },
    })
    expect(wrapper.find("details").exists()).toBe(false)
    const root = wrapper.find("div.workflow-progress.workflow-progress--expanded")
    expect(root.exists()).toBe(true)
    expect(root.attributes("data-collapse-storage-key")).toBeUndefined()
    expect(wrapper.find(".workflow-progress__chevron").exists()).toBe(false)
  })

  it("card 变体挂 workflow-progress--card；状态修饰类齐全", () => {
    const wrapper = mount(WorkflowProgressCard, {
      props: { progress: makeProgress({ failed: true }), variant: "card" },
    })
    const root = wrapper.find("details.workflow-progress")
    expect(root.classes()).toContain("workflow-progress--card")
    expect(root.classes()).toContain("workflow-progress--failed")
  })

  it("indeterminate 进度条无 aria-valuenow", () => {
    const wrapper = mount(WorkflowProgressCard, {
      props: { progress: makeProgress({ indeterminate: true, hasPercent: false }) },
    })
    expect(wrapper.find(".workflow-progress__fill--indeterminate").exists()).toBe(true)
    expect(wrapper.find(".workflow-progress__bar").attributes("aria-valuenow")).toBeUndefined()
  })
})

describe("折叠持久化", () => {
  it("默认收起（无 failed/attention），用户展开后写入 sessionStorage", async () => {
    const wrapper = mount(WorkflowProgressCard, { props: { progress: makeProgress() } })
    const details = wrapper.find("details.workflow-progress")
    expect(details.attributes("open")).toBeUndefined()

    details.element.open = true
    await details.trigger("toggle")
    expect(sessionStorage.getItem("workflow-progress-card:task-1")).toBe("open")
    expect(wrapper.find("summary").attributes("aria-label")).toContain("收起")
  })

  it("failed 时默认展开；存储 closed 优先", () => {
    const failed = mount(WorkflowProgressCard, { props: { progress: makeProgress({ failed: true }) } })
    expect(failed.find("details.workflow-progress").attributes("open")).toBeDefined()

    sessionStorage.setItem("workflow-progress-card:task-1", "closed")
    const stored = mount(WorkflowProgressCard, { props: { progress: makeProgress({ failed: true }) } })
    expect(stored.find("details.workflow-progress").attributes("open")).toBeUndefined()
  })

  it("详细进度独立持久化", async () => {
    const progress = makeProgress({
      phaseTimeline: [{ phase: "phase0_plan", status: "completed", duration_s: 3 }],
    })
    const wrapper = mount(WorkflowProgressCard, { props: { progress } })
    const details = wrapper.find("details.workflow-progress__details")
    expect(details.exists()).toBe(true)
    details.element.open = true
    await details.trigger("toggle")
    expect(sessionStorage.getItem("workflow-progress-details:task-1")).toBe("open")
  })
})

describe("开合随进度变化（vanilla 渲染期重算语义）", () => {
  it("running→failed 轮询更新自动展开并显示错误与重试区", async () => {
    const wrapper = mount(WorkflowProgressCard, { props: { progress: makeProgress() } })
    expect(wrapper.find("details.workflow-progress").attributes("open")).toBeUndefined()

    await wrapper.setProps({
      progress: makeProgress({ failed: true, errorMessage: "Embedding 服务不可用" }),
    })
    expect(wrapper.find("details.workflow-progress").attributes("open")).toBeDefined()
    expect(wrapper.text()).toContain("Embedding 服务不可用")
  })

  it("failed→running（重试后）自动收起（无存储选择时）", async () => {
    const wrapper = mount(WorkflowProgressCard, {
      props: { progress: makeProgress({ failed: true }) },
    })
    expect(wrapper.find("details.workflow-progress").attributes("open")).toBeDefined()

    await wrapper.setProps({ progress: makeProgress({ failed: false }) })
    expect(wrapper.find("details.workflow-progress").attributes("open")).toBeUndefined()
  })

  it("用户手动收起后 failed 不再自动展开", async () => {
    const wrapper = mount(WorkflowProgressCard, { props: { progress: makeProgress() } })
    const details = wrapper.find("details.workflow-progress")
    details.element.open = false
    await details.trigger("toggle")
    expect(sessionStorage.getItem("workflow-progress-card:task-1")).toBe("closed")

    await wrapper.setProps({ progress: makeProgress({ failed: true }) })
    expect(wrapper.find("details.workflow-progress").attributes("open")).toBeUndefined()
  })

  it("切换任务（新 taskId）按新存储键重算卡片与详情开合", async () => {
    const progress = makeProgress({
      phaseTimeline: [{ phase: "phase0_plan", status: "completed", duration_s: 3 }],
    })
    const wrapper = mount(WorkflowProgressCard, { props: { progress } })
    const details = wrapper.find("details.workflow-progress__details")
    details.element.open = true
    await details.trigger("toggle")
    expect(sessionStorage.getItem("workflow-progress-details:task-1")).toBe("open")

    await wrapper.setProps({
      progress: makeProgress({
        taskId: "task-2",
        failed: true,
        phaseTimeline: [{ phase: "phase0_plan", status: "completed", duration_s: 3 }],
      }),
    })
    expect(wrapper.find("details.workflow-progress").attributes("data-collapse-storage-key")).toBe("workflow-progress-card:task-2")
    expect(wrapper.find("details.workflow-progress").attributes("open")).toBeDefined()
    // task-2 详情无存储 → 回到默认（关闭）
    expect(wrapper.find("details.workflow-progress__details").attributes("open")).toBeUndefined()
  })
})

describe("内容区块", () => {
  it("资产摘要 / 阶段产物 / 警告 / 错误", () => {
    const wrapper = mount(WorkflowProgressCard, {
      props: {
        progress: makeProgress({
          resultSummary: "完成 58 条",
          errorMessage: "部分失败",
          warnings: ["警告一", "警告二", "警告三", "警告四（截断）"],
          assetSummary: { adopted: 10, review: 2, not_adopted: 1 },
          phaseArtifacts: {
            phase0_plan: { status: "completed", counts: { total_scenes: 58 } },
          },
        }),
      },
    })
    expect(wrapper.find(".workflow-progress__summary").text()).toBe("完成 58 条")
    expect(wrapper.find(".workflow-progress__error").text()).toBe("部分失败")
    expect(wrapper.findAll(".workflow-progress__warnings li")).toHaveLength(3)
    expect(wrapper.find(".workflow-progress__asset-summary").text()).toContain("已采用 10")
    expect(wrapper.find(".workflow-progress__artifacts li").text()).toContain("Phase 0 · Scene 窗口规划")
    expect(wrapper.find(".workflow-progress__artifacts li").text()).toContain("Scene 58")
  })

  it("详细进度五个小节按需渲染", () => {
    const wrapper = mount(WorkflowProgressCard, {
      props: {
        progress: makeProgress({
          phaseTimeline: [{ phase: "phase0_plan", status: "completed", duration_s: 3 }],
          progressEvents: [{ phase: "phase0_plan", event: "start", status: "running", level: "info" }],
          acceptanceChecks: [{ phase: "phase0_plan", name: "schema", ok: false, message: "字段缺失" }],
          phaseErrors: [{ phase: "phase1b_enrichment", error_kind: "timeout", message: "超时" }],
          diagnosticCounts: { candidates: 12 },
        }),
      },
    })
    const sections = wrapper.findAll(".workflow-progress__detail-section")
    expect(sections).toHaveLength(5)
    expect(wrapper.text()).toContain("阶段时间线")
    expect(wrapper.text()).toContain("门禁检查")
    expect(wrapper.find(".workflow-progress__check--failed").text()).toContain("未通过")
    expect(wrapper.find(".workflow-progress__kv").text()).toContain("candidates")
  })

  it("操作区经 slot 注入", () => {
    const wrapper = mount(WorkflowProgressCard, {
      props: { progress: makeProgress() },
      slots: { default: '<div class="workflow-progress__actions"><button class="btn btn-sm">重试任务</button></div>' },
    })
    expect(wrapper.find(".workflow-progress__actions button").text()).toBe("重试任务")
  })
})
