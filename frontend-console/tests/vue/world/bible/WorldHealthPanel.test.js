import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"

vi.mock("../../../../shared/workflowProgress.js", async (importOriginal) => {
  const original = await importOriginal()
  return { ...original, pollTaskProgress: vi.fn(() => ({ stop: vi.fn() })) }
})

const confirmAiReference = vi.hoisted(() => vi.fn())
vi.mock("../../../../shared/aiReferenceModal.js", () => ({ confirmAiReference }))

import { pollTaskProgress } from "../../../../shared/workflowProgress.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"
import WorldHealthPanel from "../../../../vue/views/world/bible/WorldHealthPanel.vue"

enableAutoUnmount(afterEach)

let api
let toast
let confirm

function completedRun(overrides = {}) {
  return {
    id: "run-1",
    novel_id: "p1",
    task_id: "task-1",
    scope: "targeted",
    status: "completed",
    verdict: "mixed",
    gate: "warn",
    receipt_hash: "a".repeat(64),
    findings: [],
    omissions: [],
    coverage_ledger: [],
    budget_ledger: {},
    warning_receipt: {},
    created_at: "2026-08-21T10:00:00Z",
    ...overrides,
  }
}

function mountPanel(props = {}) {
  return mount(WorldHealthPanel, {
    props: {
      projectId: "p1",
      targetType: "world_bible_draft",
      targetId: "draft-1",
      initialRun: null,
      ...props,
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  confirmAiReference.mockResolvedValue({ id: "confirm-default" })
  toast = vi.fn()
  confirm = vi.fn(() => true)
  api = {
    world: {
      activateWorldValidationPolicy: vi.fn(),
      createWorldValidationRun: vi.fn(),
      getWorldValidationRun: vi.fn(),
      listWorldValidationRuns: vi.fn(),
      acceptWorldValidationWarnings: vi.fn(),
      listWorldValidationFindings: vi.fn(async () => ({
        items: [], total: 0, page: 1, page_size: 20, dispositions: {},
      })),
      createWorldValidationReviewItems: vi.fn(),
      continueWorldValidationRun: vi.fn(),
      saveWorldValidationPolicyDraft: vi.fn(),
      getWorldValidationPolicyStatus: vi.fn(),
    },
    tasks: { get: vi.fn() },
  }
  setBridgeOverrides({ api, confirm, toast })
})

afterEach(() => resetBridgeOverrides())

describe("WorldHealthPanel", () => {
  it("用作者语言呈现空态和两种校验范围", () => {
    const wrapper = mountPanel()

    expect(wrapper.attributes("open")).toBeUndefined()
    expect(wrapper.text()).toContain("世界健康")
    expect(wrapper.text()).toContain("尚未校验")
    expect(wrapper.get('[data-action="world-health-run-targeted"]').text()).toContain("当前工作稿")
    expect(wrapper.get('[data-action="world-health-run-full"]').text()).toContain("全面校验")
    expect(wrapper.text()).not.toContain("receipt_hash")
  })

  it("提交前告知语义预算和超限后果", () => {
    const wrapper = mountPanel({
      policyStatus: {
        active: true,
        semantic_enabled: true,
        estimated_packets: 30,
        estimated_input_characters: 900000,
        will_exceed_budget: true,
      },
    })
    expect(wrapper.text()).toContain("30 个分片")
    expect(wrapper.text()).toContain("900,000 字符")
    expect(wrapper.text()).toContain("分批执行")
  })

  it("定向语义校验把当前工作稿放入确认资料", async () => {
    api.world.createWorldValidationRun.mockResolvedValue({
      ...completedRun(), status: "queued", gate: null,
    })
    const wrapper = mountPanel({
      policyStatus: { active: true, semantic_enabled: true },
    })

    await wrapper.get('[data-action="world-health-run-targeted"]').trigger("click")

    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({
      action: "world.validation.semantic",
      selected_world_bible_draft_ids: ["draft-1"],
    }))
    expect(api.world.createWorldValidationRun).toHaveBeenCalledWith(expect.objectContaining({
      context_confirmation_id: "confirm-default",
      target_id: "draft-1",
    }))
  })

  it("二次确认后启用发布前校验", async () => {
    api.world.activateWorldValidationPolicy.mockResolvedValue({ id: "policy-page" })
    const wrapper = mountPanel()

    await wrapper.get('[data-action="world-health-activate-policy"]').trigger("click")

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("必须先完成"))
    expect(api.world.activateWorldValidationPolicy).toHaveBeenCalledWith("p1")
    expect(wrapper.emitted("policy-updated")[0][0]).toEqual(expect.objectContaining({ active: true }))
    expect(wrapper.text()).toContain("发布前校验已启用")
  })

  it("以 operation id 提交当前工作稿并启动任务轮询", async () => {
    api.world.createWorldValidationRun.mockResolvedValue({
      ...completedRun(), status: "queued", gate: null,
    })
    const wrapper = mountPanel()

    await wrapper.get('[data-action="world-health-run-targeted"]').trigger("click")

    expect(api.world.createWorldValidationRun).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      scope: "targeted",
      target_type: "world_bible_draft",
      target_id: "draft-1",
      operation_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
    }))
    expect(pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "task-1",
      workflowType: "world_validation",
    }))
  })

  it("正典采用只提供包含采用包的全面校验", async () => {
    api.world.createWorldValidationRun.mockResolvedValue({
      ...completedRun({ scope: "full" }), status: "queued", gate: null,
    })
    const wrapper = mountPanel({
      targetType: "world_adoption_package",
      targetId: "package-1",
    })

    expect(wrapper.find('[data-action="world-health-run-targeted"]').exists()).toBe(false)
    expect(wrapper.get('[data-action="world-health-run-full"]').text()).toContain("准备采用")
    await wrapper.get('[data-action="world-health-run-full"]').trigger("click")
    expect(api.world.createWorldValidationRun).toHaveBeenCalledWith(
      expect.objectContaining({ scope: "full", novel_id: "p1" }),
    )
    expect(api.world.createWorldValidationRun.mock.calls[0][0]).not.toHaveProperty("target_id")
  })

  it("规则和策略工作稿只提供全面发布校验", () => {
    const wrapper = mountPanel({ requiresFullScope: true })
    expect(wrapper.find('[data-action="world-health-run-targeted"]').exists()).toBe(false)
    expect(wrapper.get('[data-action="world-health-run-full"]').text()).toContain("准备发布")
  })

  it("全量签收 warning 并可恢复问题来源", async () => {
    const run = completedRun({
      findings: [
        {
          finding_id: "finding-1", severity: "warning", action: "KEEP-GATE",
          category: "gap", message: "社会后果仍需核对", source_key: "draft:draft-1",
        },
      ],
    })
    api.world.acceptWorldValidationWarnings.mockResolvedValue({
      ...run,
      warning_receipt: { receipt_hash: run.receipt_hash },
    })
    api.world.listWorldValidationFindings.mockResolvedValue({
      items: run.findings, total: 1, page: 1, page_size: 20, dispositions: {},
    })
    const wrapper = mountPanel({ initialRun: run })
    await flushPromises()

    await wrapper.get('[data-action="world-health-open-source"]').trigger("click")
    expect(wrapper.emitted("open-source")[0]).toEqual([{ kind: "draft", id: "draft-1" }])

    await wrapper.get("textarea").setValue("这是作者有意保留的未决风险")
    await wrapper.get("form").trigger("submit")

    expect(api.world.acceptWorldValidationWarnings).toHaveBeenCalledWith("run-1", "p1", {
      expected_receipt_hash: run.receipt_hash,
      finding_ids: ["finding-1"],
      reason: "这是作者有意保留的未决风险",
    })
    expect(wrapper.text()).toContain("已记录作者")
  })

  it("汇总世界循环、耦合链和下游失效", async () => {
    const run = completedRun({
      findings: [
        { finding_id: "f1", severity: "error", action: "CANDIDATE", category: "reproduction-loop-gap", message: "循环缺口", location: "reproduction_loops:L1" },
        { finding_id: "f2", severity: "error", action: "CANDIDATE", category: "coupling-chain-gap", message: "耦合缺口", location: "coupling_chains:C1" },
        { finding_id: "f3", severity: "error", action: "CLOSE", category: "downstream-invalidation-missing", message: "下游未失效" },
      ],
      omissions: [{ source_key: "page:missing" }],
    })
    api.world.listWorldValidationFindings.mockResolvedValue({
      items: run.findings, total: 3, page: 1, page_size: 20, dispositions: {},
    })
    const wrapper = mountPanel({ initialRun: run })
    await flushPromises()

    expect(wrapper.text()).toContain("2项待补证据")
    expect(wrapper.text()).toContain("2项失效或不完整")
    expect(wrapper.text()).toContain("世界循环")
    expect(wrapper.text()).toContain("耦合链")
  })

  it("逐项复核：作者裁定 AUTHOR-REQUIRED 后进度更新", async () => {
    const run = completedRun({
      verdict: "author-required",
      gate: "block",
      review: { required: 1, reviewed: 0, pending_finding_ids: ["finding-a"] },
      findings: [
        { finding_id: "finding-a", severity: "error", action: "AUTHOR-REQUIRED", category: "decision", message: "待作者裁定", source_key: "draft:draft-1" },
      ],
    })
    api.world.listWorldValidationFindings.mockResolvedValue({
      items: run.findings, total: 1, page: 1, page_size: 20, dispositions: {},
    })
    api.world.createWorldValidationReviewItems.mockResolvedValue({
      ...run,
      review: { required: 1, reviewed: 1, pending_finding_ids: [] },
    })
    const wrapper = mountPanel({ initialRun: run })
    await flushPromises()

    expect(wrapper.text()).toContain("0/1项已复核")
    await wrapper.get('[data-action="review-resolved-finding-a"]').trigger("click")
    expect(api.world.createWorldValidationReviewItems).toHaveBeenCalledWith("run-1", "p1", {
      items: [{ finding_id: "finding-a", disposition: "resolved", note: "" }],
    })
    await flushPromises()
    expect(api.world.listWorldValidationFindings).toHaveBeenCalled()
  })

  it("分页与筛选走服务端 findings 接口", async () => {
    const run = completedRun({
      findings: Array.from({ length: 25 }, (_, index) => ({
        finding_id: `f${index}`, severity: index % 5 === 0 ? "error" : "warning",
        action: "KEEP-GATE", category: "gap", message: `问题 ${index}`, source_key: null,
      })),
    })
    api.world.listWorldValidationFindings.mockResolvedValue({
      items: run.findings.slice(20), total: 25, page: 2, page_size: 20, dispositions: {},
    })
    const wrapper = mountPanel({ initialRun: run })
    await flushPromises()

    expect(wrapper.text()).toContain("共 25 项")
    await wrapper.get('[data-field="world-health-filter-severity"]').setValue("error")
    expect(api.world.listWorldValidationFindings).toHaveBeenLastCalledWith("run-1", "p1", expect.objectContaining({ severity: "error", page: 1 }))
  })

  it("预算中断后可续接同一回执", async () => {
    const run = completedRun({
      status: "completed",
      verdict: "insufficient-evidence",
      gate: "block",
      omissions: ["semantic_budget_exceeded"],
      progress: { packets_planned: 8, packets_completed: 3 },
    })
    api.world.continueWorldValidationRun.mockResolvedValue({ ...run, status: "queued" })
    const wrapper = mountPanel({ initialRun: run })

    expect(wrapper.text()).toContain("已检查分片 3/8")
    await wrapper.get('[data-action="world-health-continue-run"]').trigger("click")
    expect(api.world.continueWorldValidationRun).toHaveBeenCalledWith("run-1", "p1", {})
  })

  it("定向语义查漏使用根对象一跳并发起校验", async () => {
    api.world.createWorldValidationRun.mockResolvedValue({
      ...completedRun(), status: "queued", gate: null, target_type: "semantic_gap",
    })
    const wrapper = mountPanel({
      gapRoot: { type: "world_bible_page_draft", id: "draft-1", label: "潮汐地理", selected_world_bible_draft_ids: ["draft-1"] },
      policyStatus: { active: true, semantic_enabled: true },
    })

    await wrapper.get('[data-action="world-health-semantic-gap"]').trigger("click")

    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({
      task: expect.stringContaining("潮汐地理"),
    }))
    expect(api.world.createWorldValidationRun).toHaveBeenCalledWith(expect.objectContaining({
      scope: "targeted",
      target_type: "semantic_gap",
      target_id: "draft-1",
      root_type: "world_bible_page_draft",
    }))
  })

  it("政策编辑器保存工作稿并刷新状态", async () => {
    api.world.saveWorldValidationPolicyDraft.mockResolvedValue({ id: "draft-policy" })
    api.world.getWorldValidationPolicyStatus.mockResolvedValue({
      active: false,
      draft: { draft_id: "draft-policy", policy: { policy_version: "v2" } },
    })
    const wrapper = mountPanel()

    await wrapper.get('[data-action="world-health-edit-policy"]').trigger("click")
    await wrapper.get('[data-field="world-policy-version"]').setValue("v2")
    await wrapper.get('[data-action="world-policy-rule-add"]').trigger("click")
    await wrapper.get('[data-field="world-policy-rule-op-0"]').setValue("forbid_regex")
    await wrapper.get('[data-field="world-policy-rule-value-0"]').setValue("禁止词")
    await wrapper.get('[data-field="world-policy-rule-message-0"]').setValue("不要出现禁止词")
    await wrapper.get('[data-action="world-policy-save"]').trigger("click")
    await flushPromises()

    expect(api.world.saveWorldValidationPolicyDraft).toHaveBeenCalledWith("p1", expect.objectContaining({
      policy: expect.objectContaining({
        policy_version: "v2",
        rules: [expect.objectContaining({ operator: "forbid_regex", value: "禁止词", message: "不要出现禁止词" })],
      }),
    }))
    expect(wrapper.emitted("policy-updated")[0][0]).toEqual(expect.objectContaining({ active: false }))
    expect(wrapper.text()).toContain("政策已有工作稿")
  })

  it("恢复进行中回执，且失效回执明确阻断", () => {
    const wrapper = mountPanel({
      initialRun: completedRun({ status: "stale", gate: "block" }),
    })
    expect(wrapper.attributes("open")).toBe("")
    expect(wrapper.text()).toContain("已失效")
    expect(wrapper.text()).toContain("旧回执不再能用于发布或采用")

    wrapper.setProps({ initialRun: completedRun({ status: "running", gate: null }) })
    return wrapper.vm.$nextTick().then(() => {
      expect(pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({ taskId: "task-1" }))
    })
  })
})
