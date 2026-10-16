import { afterEach, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import GoalRunsPanel from "../../../vue/components/GoalRunsPanel.vue"
import GoalPlanField from "../../../vue/components/GoalPlanField.vue"

const mocks = vi.hoisted(() => ({ api: null, locateAssistantSource: vi.fn() }))

vi.mock("../../../vue/bridge/index.js", () => ({
  getApi: () => ({ assistant: mocks.api }),
}))
vi.mock("../../../vue/shared/assistantNavigation.js", () => ({
  locateAssistantSource: mocks.locateAssistantSource,
}))

enableAutoUnmount(afterEach)

const capabilities = {
  enabled: true,
  max_steps: 30,
  budget_limits: {
    requests_max: 100,
    possible_charge_requests_max: 100,
    tokens_max: 500000,
    time_limit_seconds_max: 7200,
  },
}

function goalView(overrides = {}) {
  return {
    run_id: "internal-run-id",
    created_at: "2026-10-16T09:00:00Z",
    status: "waiting_approval",
    phase: "plan_review",
    revision: 3,
    title: "整理作者待办",
    summary: "更新选定待办",
    goal: "更新项目中的作者待办",
    plan: {
      title: "整理作者待办",
      summary: "更新选定待办",
      steps: [
        {
          step_id: "internal-step-id",
          operation_id: "project.update_task",
          depends_on: [],
          targets: [{ target_type: "author_task", target_id: "internal-target-id" }],
          parameters: {
            task_id: "internal-target-id",
            changes: { title: "更新后的标题" },
          },
          intent: "更新作者待办标题",
        },
      ],
    },
    steps: [
      {
        step_id: "internal-step-id",
        operation_id: "project.update_task",
        label: "更新作者待办",
        description: "只修改作者待办，不改变作品事实。",
        risk: "R2",
        risk_label: "可恢复的修改",
        fee_category: "free",
        fee_label: "不调用模型",
        target_type: "author_task",
        target_count: 1,
        dependency_labels: [],
        status: "pending",
        status_label: "待执行",
        preview_summary: "更新待办标题",
        diff: [{ field: "标题", before: "原始标题", after: "更新后的标题" }],
        fields: [
          {
            name: "task_id",
            label: "待办",
            kind: "identifier",
            value: "internal-target-id",
            editable: false,
            children: [],
          },
          {
            name: "changes",
            label: "修改内容",
            kind: "object",
            value: { title: "更新后的标题" },
            editable: true,
            children: [],
          },
        ],
        can_confirm: false,
      },
    ],
    progress: { completed: 0, total: 1 },
    budget: {
      initial_limits: {
        requests: 8,
        possible_charge_requests: 8,
        tokens: 12000,
        time_limit_seconds: 1200,
      },
      limits: {
        requests: 8,
        possible_charge_requests: 8,
        tokens: 12000,
        time_limit_seconds: 1200,
      },
      used: {
        requests: 1,
        possible_charge_requests: 1,
        tokens: 20,
        charge_state: "recorded",
      },
    },
    auto_r2: false,
    can_approve_plan: true,
    can_resume: false,
    can_advance: false,
    can_pause: true,
    can_replan: false,
    can_cancel: true,
    can_restore: false,
    changes: [],
    replan_changes: [],
    diagnostics: { planning_error: null },
    ...overrides,
  }
}

function setupApi(overrides = {}) {
  mocks.api = {
    goalCapabilities: vi.fn().mockResolvedValue(capabilities),
    recentGoals: vi.fn().mockResolvedValue([]),
    goal: vi.fn(),
    startGoal: vi.fn(),
    approveGoal: vi.fn(),
    approveGoalStep: vi.fn(),
    reconcileGoalStep: vi.fn(),
    goalStepReceiptPreview: vi.fn(),
    advanceGoal: vi.fn(),
    pauseGoal: vi.fn(),
    resumeGoal: vi.fn(),
    cancelGoal: vi.fn(),
    replanGoal: vi.fn(),
    restoreGoal: vi.fn(),
    ...overrides,
  }
  return mocks.api
}

async function mountedPanel(_api = setupApi(), props = {}) {
  const wrapper = mount(GoalRunsPanel, {
    props: { projectId: "project-1", active: true, ...props },
  })
  await flushPromises()
  return wrapper
}

afterEach(() => {
  vi.unstubAllGlobals()
  mocks.api = null
  mocks.locateAssistantSource.mockReset()
})

it("explains operations that the goal planner cannot execute", async () => {
  const api = setupApi({
    goalCapabilities: vi.fn().mockResolvedValue({
      ...capabilities,
      unavailable_operations: [
        {
          operation_id: "story.plan_structure",
          label: "准备故事结构",
          reason: "模型费用尚未接入目标根预算",
        },
      ],
    }),
  })
  const wrapper = await mountedPanel(api)

  expect(wrapper.get(".goal-runs-start details summary").text()).toContain("1 项操作暂不能纳入目标计划")
  expect(wrapper.get(".goal-runs-start details li").text()).toContain("准备故事结构：模型费用尚未接入目标根预算")
})

it("accepts the default and saved integer token budgets in native forms", async () => {
  const start = await mountedPanel()
  expect(start.get('.goal-runs-start input[type="number"][step="1"]').element.value).toBe("12000")
  expect(start.get(".goal-runs-start").element.checkValidity()).toBe(true)

  const api = setupApi({ recentGoals: vi.fn().mockResolvedValue([goalView()]) })
  const review = await mountedPanel(api)
  expect(review.get(".goal-runs-plan").element.checkValidity()).toBe(true)
})

it("uses translated plan option labels and hides unsupported internal enum values", () => {
  const translated = mount(GoalPlanField, {
    props: {
      field: {
        name: "action",
        label: "处理方式",
        kind: "text",
        enum_options: [{ value: "adopt", label: "采用" }],
        editable: true,
      },
      value: "adopt",
      fieldId: "action",
    },
  })
  expect(translated.text()).toContain("采用")
  expect(translated.text()).not.toContain("adopt")

  const unsupported = mount(GoalPlanField, {
    props: {
      field: {
        name: "private_mode",
        label: "处理范围",
        kind: "text",
        locked_reason: "此选项需在原工作台处理",
        editable: false,
      },
      value: "internal_only",
      fieldId: "private-mode",
    },
  })
  expect(unsupported.text()).toContain("此选项需在原工作台处理")
  expect(unsupported.text()).not.toContain("internal_only")
})

it("blocks plan approval when an option cannot be reviewed safely in this panel", async () => {
  const current = goalView()
  current.steps[0].fields.push({
    name: "private_mode",
    label: "范围",
    kind: "text",
    value: "internal_only",
    editable: false,
    locked_reason: "此选项需在原工作台处理",
  })
  const api = setupApi({ recentGoals: vi.fn().mockResolvedValue([current]) })
  const wrapper = await mountedPanel(api)

  expect(wrapper.text()).toContain("有些目录选项还不能在此确认")
  expect(wrapper.text()).not.toContain("internal_only")
  expect(wrapper.get("form.goal-runs-plan button[type=submit]").element.disabled).toBe(true)
})

it("requires explicit budget acknowledgement and sends an idempotent goal request", async () => {
  vi.stubGlobal("crypto", { randomUUID: () => "request-id-1" })
  const planReview = goalView()
  const api = setupApi({ startGoal: vi.fn().mockResolvedValue(planReview) })
  const wrapper = await mountedPanel(api, { sourceSessionId: "source-session" })

  await wrapper.get("#goal-run-prompt").setValue("更新当前项目的作者待办")
  const startForm = wrapper.get("form.goal-runs-start")
  expect(startForm.get("button[type='submit']").attributes("disabled")).toBeDefined()
  await wrapper.find(".goal-runs-consent input").setValue(true)
  await startForm.trigger("submit")
  await flushPromises()

  expect(api.startGoal).toHaveBeenCalledExactlyOnceWith({
    novel_id: "project-1",
    request_id: "request-id-1",
    goal: "更新当前项目的作者待办",
    budget: {
      requests: 8,
      possible_charge_requests: 8,
      tokens: 12000,
      time_limit_seconds: 1200,
    },
    source_session_id: "source-session",
  })
  expect(wrapper.text()).toContain("审阅计划")
  expect(wrapper.text()).not.toContain("internal-run-id")
  expect(wrapper.text()).not.toContain("internal-step-id")
  expect(wrapper.text()).not.toContain("internal-target-id")
  expect(wrapper.text()).not.toContain("project.update_task")
})

it("submits edited plan fields and an explicit R2 automation choice", async () => {
  const planReview = goalView()
  const completed = goalView({
    status: "completed",
    phase: "completed",
    can_approve_plan: false,
    can_pause: false,
    can_cancel: false,
    can_replan: false,
  })
  const api = setupApi({
    recentGoals: vi.fn().mockResolvedValue([planReview]),
    approveGoal: vi.fn().mockResolvedValue(completed),
  })
  const wrapper = await mountedPanel(api)

  await wrapper.get(".goal-runs-plan input").setValue("重新整理待办")
  await wrapper.get(".goal-runs-consent--r2 input").setValue(true)
  await wrapper.get(".goal-runs-plan").trigger("submit")
  await flushPromises()

  const [, , body] = api.approveGoal.mock.calls[0]
  expect(body.expected_revision).toBe(3)
  expect(body.plan.title).toBe("重新整理待办")
  expect(body.plan.steps[0].parameters.changes.title).toBe("更新后的标题")
  expect(body.auto_r2).toBe(true)
  expect(wrapper.text()).toContain("已完成")
})

it("retains an unsent replan reason when the server returns 409", async () => {
  const stale = goalView({
    phase: "stopped",
    can_approve_plan: false,
    can_replan: true,
    can_cancel: true,
  })
  const latest = goalView({ ...stale, revision: 4, stop_reason: "状态刚刚更新" })
  let reads = 0
  const api = setupApi({
    recentGoals: vi.fn().mockImplementation(async () => (++reads === 1 ? [stale] : [latest])),
    replanGoal: vi.fn().mockRejectedValue(Object.assign(new Error("conflict"), { status: 409 })),
  })
  const wrapper = await mountedPanel(api)
  await wrapper.get(".goal-runs-replan textarea").setValue("把依赖缩小到一个待办")
  await wrapper.get(".goal-runs-replan").trigger("submit")
  await flushPromises()

  expect(wrapper.get(".goal-runs-error").text()).toContain("目标状态已更新")
  expect(wrapper.get(".goal-runs-replan textarea").element.value).toBe("把依赖缩小到一个待办")
  expect(api.recentGoals).toHaveBeenCalledTimes(2)
})

it("shows a confirmed R3 stop and keeps recovery options visible", async () => {
  const waitingStep = goalView({
    phase: "step_review",
    stop_reason: "这一步需要单独确认。",
    stop_reason_label: "这一步需要单独确认。",
    can_approve_plan: false,
    can_pause: true,
    can_cancel: true,
    can_restore: true,
    steps: [
      {
        ...goalView().steps[0],
        risk: "R3",
        risk_label: "影响采用或正式内容",
        can_confirm: true,
        status: "prepared",
        status_label: "已准备，等待作者确认",
      },
    ],
    changes: [
      {
        label: "更新作者待办",
        state: "applied",
        state_label: "已自动修改",
        summary: "待办字段更新；恢复前会检查作者后续编辑。",
        can_restore: true,
      },
    ],
  })
  const api = setupApi({ recentGoals: vi.fn().mockResolvedValue([waitingStep]) })
  const wrapper = await mountedPanel(api)

  expect(wrapper.text()).toContain("确认并执行这一步")
  expect(wrapper.text()).toContain("恢复可恢复的修改")
  expect(wrapper.text()).toContain("取消不会撤销已完成修改")
})

it("lets the author keep an unknown result blocked or confirm a checked receipt", async () => {
  const unknown = goalView({
    phase: "stopped",
    stop_code: "task_outcome_unknown",
    stop_reason: "原领域回执仍无法确认。",
    can_approve_plan: false,
    can_replan: false,
    can_pause: false,
    steps: [{
      ...goalView().steps[0],
      status: "outcome_unknown",
      status_label: "结果待核对",
      can_confirm: false,
      can_reconcile: true,
    }],
  })
  const stillUnknown = goalView({
    ...unknown,
    revision: 4,
    steps: unknown.steps.map(step => ({ ...step, status: "outcome_unknown" })),
  })
  const api = setupApi({
    recentGoals: vi.fn().mockResolvedValue([unknown]),
    reconcileGoalStep: vi.fn().mockResolvedValue(stillUnknown),
  })
  const wrapper = await mountedPanel(api)

  expect(wrapper.text()).toContain("读取这一步保存的领域回执")
  expect(wrapper.text()).toContain("不会重放操作")
  expect(wrapper.text()).toContain("已用额度也不会重置或返还")
  await wrapper.get(".goal-runs-reconciliation button:last-child").trigger("click")
  await flushPromises()

  expect(api.reconcileGoalStep).toHaveBeenCalledExactlyOnceWith(
    "project-1",
    "internal-run-id",
    "internal-step-id",
    { expected_revision: 3, decision: "still_unknown" },
  )
  expect(wrapper.text()).not.toContain("internal-run-id")
  expect(wrapper.text()).not.toContain("internal-step-id")
})

it("shows the verified domain result before allowing a conclusive decision", async () => {
  const candidateId = "f4ea4bb6-5bf3-4a8b-9403-76cb62e6d5c1"
  const unknown = goalView({
    phase: "stopped",
    stop_code: "task_outcome_unknown",
    stop_reason: "原领域回执仍无法确认。",
    can_approve_plan: false,
    can_replan: false,
    can_pause: false,
    steps: [{
      ...goalView().steps[0],
      status: "outcome_unknown",
      status_label: "结果待核对",
      can_confirm: false,
      can_reconcile: true,
    }],
  })
  const api = setupApi({
    recentGoals: vi.fn().mockResolvedValue([unknown]),
    goalStepReceiptPreview: vi.fn().mockResolvedValue({
      expected_revision: 3,
      status: "verified_applied",
      summary: "第 4 章的正文候选已生成：《候选标题》",
      details: ["候选仍需在写作工作台审阅；生成完成不代表已采用。"],
      available_decisions: ["applied"],
      destination: {
        kind: "writing_candidate",
        candidate_id: candidateId,
        chapter_index: 4,
      },
    }),
    reconcileGoalStep: vi.fn().mockResolvedValue(unknown),
  })
  const wrapper = await mountedPanel(api)

  expect(wrapper.text()).not.toContain("确认：原操作已完成")
  expect(wrapper.text()).not.toContain("确认：原操作未应用")
  await wrapper.get(".goal-runs-reconciliation button").trigger("click")
  await flushPromises()

  expect(api.goalStepReceiptPreview).toHaveBeenCalledExactlyOnceWith(
    "project-1",
    "internal-run-id",
    "internal-step-id",
    3,
  )
  expect(wrapper.text()).toContain("原领域回执已核实为已完成")
  expect(wrapper.text()).toContain("候选标题")
  expect(wrapper.text()).toContain("确认：原操作已完成")
  expect(wrapper.text()).not.toContain("确认：原操作未应用")
  expect(wrapper.text()).not.toContain(candidateId)
  let reconciliationButtons = wrapper.findAll(".goal-runs-reconciliation button")
  await reconciliationButtons[0].trigger("click")
  expect(mocks.locateAssistantSource).toHaveBeenCalledExactlyOnceWith({
    type: "writing_candidate",
    id: candidateId,
    chapter_index: 4,
  })
  reconciliationButtons = wrapper.findAll(".goal-runs-reconciliation button")
  await reconciliationButtons[1].trigger("click")
  await flushPromises()
  expect(api.reconcileGoalStep).toHaveBeenCalledExactlyOnceWith(
    "project-1",
    "internal-run-id",
    "internal-step-id",
    { expected_revision: 3, decision: "applied" },
  )
})

it("keeps inconclusive receipt previews blocked with only still-unknown available", async () => {
  const unknown = goalView({
    steps: [{
      ...goalView().steps[0],
      status: "outcome_unknown",
      status_label: "结果待核对",
      can_confirm: false,
      can_reconcile: true,
    }],
  })
  const api = setupApi({
    recentGoals: vi.fn().mockResolvedValue([unknown]),
    goalStepReceiptPreview: vi.fn().mockResolvedValue({
      expected_revision: 3,
      status: "incomplete",
      summary: "原领域结果尚不完整，仍无法确认这一步是否完成。",
      details: [],
      available_decisions: [],
      destination: null,
    }),
  })
  const wrapper = await mountedPanel(api)

  await wrapper.get(".goal-runs-reconciliation button").trigger("click")
  await flushPromises()

  expect(wrapper.text()).toContain("原领域结果尚不完整")
  expect(wrapper.text()).not.toContain("确认：原操作已完成")
  expect(wrapper.text()).not.toContain("确认：原操作未应用")
  expect(wrapper.text()).toContain("仍无法确认")
})

it("shows not-applied only after a matching terminal receipt is verified", async () => {
  const unknown = goalView({
    steps: [{
      ...goalView().steps[0],
      status: "outcome_unknown",
      status_label: "结果待核对",
      can_confirm: false,
      can_reconcile: true,
    }],
  })
  const api = setupApi({
    recentGoals: vi.fn().mockResolvedValue([unknown]),
    goalStepReceiptPreview: vi.fn().mockResolvedValue({
      expected_revision: 3,
      status: "verified_not_applied",
      summary: "原领域回执明确记录该操作未应用。",
      details: [],
      available_decisions: ["not_applied"],
      destination: null,
    }),
    reconcileGoalStep: vi.fn().mockResolvedValue(unknown),
  })
  const wrapper = await mountedPanel(api)

  await wrapper.get(".goal-runs-reconciliation button").trigger("click")
  await flushPromises()

  expect(wrapper.text()).toContain("原领域回执已核实为未应用")
  expect(wrapper.text()).not.toContain("确认：原操作已完成")
  expect(wrapper.text()).toContain("确认：原操作未应用")
  const reconciliationButtons = wrapper.findAll(".goal-runs-reconciliation button")
  await reconciliationButtons[0].trigger("click")
  await flushPromises()
  expect(api.reconcileGoalStep).toHaveBeenCalledExactlyOnceWith(
    "project-1",
    "internal-run-id",
    "internal-step-id",
    { expected_revision: 3, decision: "not_applied" },
  )
})
