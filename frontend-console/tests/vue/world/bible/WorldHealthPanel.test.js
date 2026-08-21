import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"

vi.mock("../../../../shared/workflowProgress.js", async (importOriginal) => {
  const original = await importOriginal()
  return { ...original, pollTaskProgress: vi.fn(() => ({ stop: vi.fn() })) }
})

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
  toast = vi.fn()
  confirm = vi.fn(() => true)
  api = {
    world: {
      activateWorldValidationPolicy: vi.fn(),
      createWorldValidationRun: vi.fn(),
      getWorldValidationRun: vi.fn(),
      listWorldValidationRuns: vi.fn(),
      acceptWorldValidationWarnings: vi.fn(),
    },
    tasks: { get: vi.fn() },
  }
  setBridgeOverrides({ api, confirm, toast })
})

afterEach(() => resetBridgeOverrides())

describe("WorldHealthPanel", () => {
  it("用作者语言呈现空态和两种校验范围", () => {
    const wrapper = mountPanel()

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
    expect(wrapper.text()).toContain("证据不足")
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
    const wrapper = mountPanel({ initialRun: run })

    await wrapper.get(".world-health-findings button").trigger("click")
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

  it("汇总世界循环、耦合链和下游失效", () => {
    const wrapper = mountPanel({
      initialRun: completedRun({
        findings: [
          { finding_id: "f1", severity: "error", action: "CANDIDATE", category: "reproduction-loop-gap", message: "循环缺口", location: "reproduction_loops:L1" },
          { finding_id: "f2", severity: "error", action: "CANDIDATE", category: "coupling-chain-gap", message: "耦合缺口", location: "coupling_chains:C1" },
          { finding_id: "f3", severity: "error", action: "CLOSE", category: "downstream-invalidation-missing", message: "下游未失效" },
        ],
        omissions: [{ source_key: "page:missing" }],
      }),
    })

    expect(wrapper.text()).toContain("2项待补证据")
    expect(wrapper.text()).toContain("2项失效或不完整")
    expect(wrapper.text()).toContain("世界循环")
    expect(wrapper.text()).toContain("耦合链")
  })

  it("恢复进行中回执，且失效回执明确阻断", () => {
    const wrapper = mountPanel({
      initialRun: completedRun({ status: "stale", gate: "block" }),
    })
    expect(wrapper.text()).toContain("已失效")
    expect(wrapper.text()).toContain("旧回执不再能用于发布或采用")

    wrapper.setProps({ initialRun: completedRun({ status: "running", gate: null }) })
    return wrapper.vm.$nextTick().then(() => {
      expect(pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({ taskId: "task-1" }))
    })
  })
})
