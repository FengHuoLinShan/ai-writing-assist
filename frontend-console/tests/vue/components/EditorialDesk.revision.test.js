/**
 * EditorialDesk 批注修订桥接测试（BR-4 流程 3）：
 * 选中意见 → 填处置说明 → 发起修订 → 逐条查看受理结果与替换候选。
 */
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import EditorialDesk from "../../../vue/components/EditorialDesk.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

vi.mock("../../../vue/shared/assistantNavigation.js", () => ({ locateAssistantSource: vi.fn(), openAssistantDestination: vi.fn() }))

enableAutoUnmount(afterEach)

const BRIEF = {
  version: 1,
  brief: {
    target_readers: "", genre_promise: "", goals: [], voice: "",
    preserve: [], intentional_choices: [], excluded_targets: [],
  },
}
const POLICY = { feature_available: true, enabled: false, automatic_available: true, excluded_chapters: [], generation: 1 }

function review(id = "rev-1") {
  return {
    id, status: "completed", scope: { scope: "chapter", start_chapter: 1 },
    checked_chapters: [1], unchecked_chapters: [], missing: [],
    context_sources: [], context_omissions: [],
    report: { summary: "", top_findings: [], all_findings: [] },
    error: null, brief_changed: false,
  }
}

function issue(id, { version = 0, reviewId = "rev-1" } = {}) {
  return {
    id,
    fingerprint: `fp-${id}`,
    review_id: reviewId,
    version,
    disposition: "open",
    finding: {
      category: "line",
      judgment: `意见 ${id}`,
      reader_impact: "读者可能出戏",
      severity: "medium",
      evidence: [{ chapter_index: 1, quote: "原文片段", draft_id: "d1", content_hash: "h1", start: 0, end: 4 }],
      context_evidence: [],
      unchecked: "",
      directions: [],
    },
    decisions: [],
    rechecks: [],
    history: [],
    source_may_be_stale: false,
  }
}

let apiMock

beforeEach(() => {
  apiMock = {
    projects: {
      editorialBrief: vi.fn(async () => BRIEF),
      saveEditorialBrief: vi.fn(async (_projectId, body) => ({ version: 2, brief: body.brief })),
      editorialBriefForWriting: vi.fn(async () => ({ enabled: false, brief: null })),
      setEditorialBriefForWriting: vi.fn(async (_projectId, enabled) => ({ enabled })),
    },
    assistant: {
      editorialPolicy: vi.fn(async () => POLICY),
      editorialReviews: vi.fn(async () => [review()]),
      editorialIssues: vi.fn(async () => [issue("issue-1"), issue("issue-2")]),
      reviseEditorialIssues: vi.fn(async () => ({
        operation_id: "op-1",
        items: [
          { issue_id: "issue-1", status: "queued", task_id: "task-1", chapter_index: 1 },
          { issue_id: "issue-2", status: "unlocatable", chapter_index: 1, reason: "意见引文已不在当前稿中，无法定位" },
        ],
      })),
    },
    tasks: {
      get: vi.fn(async () => ({
        task_id: "task-1", task_type: "writing_comment_run", status: "running",
        result: null, error_message: null,
      })),
    },
  }
  setBridgeOverrides({ api: apiMock, confirm: vi.fn(() => true), state: { currentProjectId: "p1" } })
})

afterEach(() => resetBridgeOverrides())

async function mountDesk() {
  const wrapper = mount(EditorialDesk, { props: { projectId: "p1", active: true } })
  await flushPromises()
  return wrapper
}

function issueCard(wrapper, issueId) {
  const card = wrapper.findAll(".editorial-issue").find((item) => item.text().includes(`意见 ${issueId}`))
  if (!card) throw new Error(`意见卡 ${issueId} 未找到`)
  return card
}

async function selectIssue(wrapper, issueId) {
  await issueCard(wrapper, issueId).find("input[type='checkbox']").setValue(true)
  await flushPromises()
}

function revisionPanel(wrapper) {
  return wrapper.find(".editorial-desk__revision")
}

describe("EditorialDesk 批注修订桥接", () => {
  it("未选意见时不显示修订面板；未填处置说明时不能提交", async () => {
    const wrapper = await mountDesk()
    expect(revisionPanel(wrapper).exists()).toBe(false)

    await selectIssue(wrapper, "issue-1")
    expect(revisionPanel(wrapper).exists()).toBe(true)
    expect(revisionPanel(wrapper).text()).toContain("按选中的 1 条意见发起批注修订")

    const submit = revisionPanel(wrapper).findAll("button").find((item) => item.text().includes("发起 1 条修订"))
    expect(submit.attributes("disabled")).toBeDefined()
  })

  it("提交携带选中意见、乐观版本与处置说明；逐条显示受理结果", async () => {
    const wrapper = await mountDesk()
    await selectIssue(wrapper, "issue-1")
    await selectIssue(wrapper, "issue-2")
    await revisionPanel(wrapper).find("textarea").setValue("把线索改得更隐晦")
    await revisionPanel(wrapper).findAll("button").find((item) => item.text().includes("发起 2 条修订")).trigger("click")
    await flushPromises()

    expect(apiMock.assistant.reviseEditorialIssues).toHaveBeenCalledWith({
      novel_id: "p1",
      operation_id: expect.any(String),
      items: [
        { issue_id: "issue-1", expected_version: 0, instruction: "把线索改得更隐晦" },
        { issue_id: "issue-2", expected_version: 0, instruction: "把线索改得更隐晦" },
      ],
    })
    const results = revisionPanel(wrapper).find(".editorial-desk__revision-results").text()
    expect(results).toContain("修订进行中…")
    expect(results).toContain("意见引文已不在当前稿中，无法定位")
    // 提交后清空选择，但结果仍在
    expect(issueCard(wrapper, "issue-1").find("input[type='checkbox']").element.checked).toBe(false)
  })

  it("轮询到任务完成后给出替换候选入口；失败任务说明原因", async () => {
    vi.useFakeTimers()
    let wrapper
    try {
      wrapper = await mountDesk()
      await selectIssue(wrapper, "issue-1")
      await revisionPanel(wrapper).find("textarea").setValue("改写")
      await revisionPanel(wrapper).findAll("button").find((item) => item.text().includes("发起 1 条修订")).trigger("click")
      await flushPromises()
      expect(apiMock.tasks.get).toHaveBeenCalledWith("task-1", "p1")
      expect(revisionPanel(wrapper).text()).toContain("修订进行中…")

      apiMock.tasks.get.mockResolvedValue({
        task_id: "task-1", task_type: "writing_comment_run", status: "done",
        result: { candidate_draft_id: "draft-9" }, error_message: null,
      })
      vi.advanceTimersByTime(8000)
      await flushPromises()
      expect(revisionPanel(wrapper).text()).toContain("替换候选已生成")
      expect(revisionPanel(wrapper).text()).toContain("去写作页审阅并采用")
    } finally {
      vi.useRealTimers()
    }

    // 失败的任务显示原因而不是入口
    apiMock.assistant.reviseEditorialIssues.mockResolvedValue({
      operation_id: "op-2",
      items: [{ issue_id: "issue-1", status: "queued", task_id: "task-2", chapter_index: 1 }],
    })
    apiMock.tasks.get.mockResolvedValue({
      task_id: "task-2", task_type: "writing_comment_run", status: "failed",
      result: null, error_message: "正文已变化，请重新提交批注任务",
    })
    await selectIssue(wrapper, "issue-1")
    await revisionPanel(wrapper).find("textarea").setValue("再改一次")
    await revisionPanel(wrapper).findAll("button").find((item) => item.text().includes("发起 1 条修订")).trigger("click")
    await flushPromises()
    expect(revisionPanel(wrapper).text()).toContain("正文已变化，请重新提交批注任务")
    expect(revisionPanel(wrapper).text()).not.toContain("去写作页审阅并采用")
  })

  it("提交失败时在面板内显示错误并保留选择", async () => {
    const wrapper = await mountDesk()
    await selectIssue(wrapper, "issue-1")
    apiMock.assistant.reviseEditorialIssues.mockRejectedValue(new Error("审读依据的正文已变化，请重新审读"))
    await revisionPanel(wrapper).find("textarea").setValue("改写")
    await revisionPanel(wrapper).findAll("button").find((item) => item.text().includes("发起 1 条修订")).trigger("click")
    await flushPromises()

    expect(revisionPanel(wrapper).text()).toContain("审读依据的正文已变化，请重新审读")
    expect(issueCard(wrapper, "issue-1").find("input[type='checkbox']").element.checked).toBe(true)
  })
})

describe("EditorialDesk 修订引导流程入口（BR-4 流程 3）", () => {
  function flowStopView(overrides = {}) {
    return {
      run_id: "flow-1",
      flow_id: "editorial_revision",
      flow_version: 1,
      title: "按审读意见定向修订",
      description: "从审读台选中的意见开始。",
      status: "waiting_approval",
      stop: {
        step_id: "review_candidates",
        kind: "author_choice",
        reason: "已生成 1 个替换候选，待你在写作页审阅采用；已采用 0 个。",
        actions: [
          { action: "open_candidate", label: "去审阅候选" },
          { action: "proceed", label: "对已采用的发起改后复核" },
          { action: "abandon_flow", label: "结束流程" },
        ],
      },
      steps: [
        { step_id: "select_issues", title: "选择意见并说明处置", state: "done", detail: "" },
        { step_id: "bridge_revision", title: "发起批注修订", state: "done", detail: "" },
        { step_id: "review_candidates", title: "审阅替换候选", state: "active", detail: "" },
      ],
      panel: {
        items: [
          { issue_id: "issue-1", status: "queued", chapter_index: 1, reason: "", candidate_draft_id: "draft-9", kind: "ready" },
        ],
        unlocatable_count: 0,
        rechecks: [],
      },
      settings: {},
      ...overrides,
    }
  }

  beforeEach(() => {
    apiMock.assistant.capabilities = vi.fn(async () => ({ guided_flows: { available: true } }))
    apiMock.assistant.guidedFlowStart = vi.fn(async () => flowStopView({ status: "running", stop: null }))
    apiMock.assistant.guidedFlowAdvance = vi.fn(async () => flowStopView())
    apiMock.assistant.guidedFlow = vi.fn(async () => flowStopView())
    apiMock.assistant.guidedFlowAbandon = vi.fn(async () => ({ status: "cancelled" }))
  })

  it("引导流程未开放时入口不可用，直接发起修订不受影响", async () => {
    apiMock.assistant.capabilities = vi.fn(async () => ({ guided_flows: { available: false } }))
    const wrapper = await mountDesk()
    await selectIssue(wrapper, "issue-1")
    const flowButton = revisionPanel(wrapper).findAll("button").find((item) => item.text().includes("走引导流程修订"))
    expect(flowButton.attributes("disabled")).toBeDefined()
  })

  it("走引导流程：选中意见打包为选择输入推进，停点给出候选与复核动作", async () => {
    const wrapper = await mountDesk()
    await selectIssue(wrapper, "issue-1")
    await revisionPanel(wrapper).find("textarea").setValue("按上下文改写")
    await revisionPanel(wrapper).findAll("button").find((item) => item.text().includes("走引导流程修订")).trigger("click")
    await flushPromises()

    expect(apiMock.assistant.guidedFlowStart).toHaveBeenCalledWith({
      novel_id: "p1",
      flow_id: "editorial_revision",
    })
    expect(apiMock.assistant.guidedFlowAdvance).toHaveBeenCalledWith("flow-1", {
      novel_id: "p1",
      choice: {
        step_id: "select_issues",
        action: "select_issues",
        items: [{ issue_id: "issue-1", expected_version: 0, instruction: "按上下文改写" }],
      },
    })
    const strip = wrapper.find(".editorial-desk__flowstrip")
    expect(strip.exists()).toBe(true)
    expect(strip.text()).toContain("已生成 1 个替换候选")
    expect(strip.text()).not.toContain("editorial_revision")
    expect(strip.text()).not.toContain("review_candidates")
  })

  it("停点动作：打开候选走写作页定位，改后复核完成后展示结论", async () => {
    const { locateAssistantSource } = await import("../../../vue/shared/assistantNavigation.js")
    locateAssistantSource.mockClear()
    const wrapper = await mountDesk()
    await selectIssue(wrapper, "issue-1")
    await revisionPanel(wrapper).find("textarea").setValue("改")
    await revisionPanel(wrapper).findAll("button").find((item) => item.text().includes("走引导流程修订")).trigger("click")
    await flushPromises()

    await wrapper.get('[data-action="flow-open_candidate"]').trigger("click")
    expect(locateAssistantSource).toHaveBeenCalledWith(expect.objectContaining({
      type: "writing_draft",
      id: "draft-9",
      chapter_index: 1,
    }))

    apiMock.assistant.guidedFlowAdvance.mockResolvedValue(flowStopView({
      status: "waiting_approval",
      stop: {
        step_id: "review_rechecks",
        kind: "author_choice",
        reason: "改后复核结果已就绪。",
        actions: [{ action: "finish_flow", label: "完成流程" }],
      },
      panel: {
        items: [],
        unlocatable_count: 0,
        rechecks: [
          { issue_id: "issue-1", status: "done", verdict: "possibly_improved", verdict_label: "可能改善", reason: "引文处已按处置改写" },
        ],
      },
    }))
    await wrapper.get('[data-action="flow-proceed"]').trigger("click")
    await flushPromises()
    expect(wrapper.find(".editorial-desk__flowstrip").text()).toContain("可能改善")
  })
})
