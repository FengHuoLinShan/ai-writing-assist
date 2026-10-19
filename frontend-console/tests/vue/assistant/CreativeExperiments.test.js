import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import CreativeExperiments from "../../../vue/components/CreativeExperiments.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { ACCOUNT_MARKER_KEY } from "../../../shared/accountStorage.js"

enableAutoUnmount(afterEach)

beforeEach(() => localStorage.clear())
afterEach(() => { resetBridgeOverrides(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it("B10-F1: 采用和检查确认先显示作者可读范围，技术回执留在次级详情", async () => {
  const receiptId = "10000000-0000-0000-0000-000000000001"
  const source = { key: "source-1", kind: "writing_draft", label: "第 2 章正文", revision: 3, source_hash: "a".repeat(64) }
  const trial = { id: "trial-a", label: "保留主角动机", status: "sealed", stale: false, revision_id: "revision-a", changes: [{ resource: { kind: "writing_draft", id: "draft-a" }, label: "第 2 章正文", operation: "replace", before: "旧稿", after: "试改" }], can_seal: false }
  const saved = {
    caseId: "case-a",
    goal: "保留主角动机",
    mergePending: { workspaceId: trial.id, caseId: "case-a", attempted: false, preview: { check_receipt_id: receiptId, read_set: [source], patch_set: [{ key: "change-1" }] }, body: {} },
    trialCheckPending: {
      workspaceId: trial.id,
      caseId: "case-a",
      attempted: false,
      request: {},
      preview: { selected_material_count: 1, estimated_selected_material_tokens: 1200, manifest_fingerprint: "b".repeat(64), case_requests_used: 2, case_request_limit: 60, run_request_limit: 10, minimum_requests_required: 2, task_request_limit: 8, task_deadline_seconds: 90, provider: "provider-name", model: "model-name", role_snapshot_fingerprints: { member: "member-fingerprint", check: "check-fingerprint" } },
    },
  }
  localStorage.setItem(ACCOUNT_MARKER_KEY, "account-a")
  localStorage.setItem("novel_creative_v2:account-a:project-a", JSON.stringify(saved))

  const api = {
    capabilities: vi.fn(async () => ({ enabled: true, recipes: [] })),
    cases: vi.fn(async () => ({ items: [] })),
    getCase: vi.fn(async () => ({ id: "case-a", goal: saved.goal, constraints: [], recipe: { id: "revision" }, grant: { resources: [], follow_changes: false }, requests_used: 2, goal_version: 1 })),
    runs: vi.fn(async () => ({ items: [] })),
    workspaces: vi.fn(async () => ({ items: [trial] })),
    diff: vi.fn(async () => trial),
    merge: vi.fn(),
  }
  setBridgeOverrides({ api: { collaboration: api } })

  const wrapper = mount(CreativeExperiments, { props: { projectId: "project-a" }, global: { stubs: { CognitionPanel: true, CreativeTrialEditor: true } } })
  await flushPromises()

  const adoption = wrapper.get('[aria-label="采用修改前的资料核对"]')
  const adoptionSummary = adoption.find("p").text()
  expect(adoptionSummary).toContain("已核对 1 项参考资料")
  expect(adoptionSummary).toContain("保存 1 项修改")
  expect(adoptionSummary).not.toContain("R3")
  expect(adoptionSummary).not.toContain(receiptId)
  expect(adoptionSummary).not.toContain("writing_draft")
  expect(wrapper.findAll("button").some(item => item.text() === "确认采用这组修改")).toBe(true)
  expect(wrapper.get(".creative-diff .creative-confirm p").text()).not.toMatch(/原子|读集/)
  expect(api.merge).not.toHaveBeenCalled()
  expect(adoption.get("details").element.open).toBe(false)
  expect(adoption.get("details").text()).toContain(receiptId)
  expect(adoption.get("details").text()).toContain(source.source_hash)

  const budget = wrapper.get('[aria-label="检查试改的预算确认"]')
  const budgetSummary = budget.findAll("p").slice(0, 2).map(item => item.text()).join(" ")
  expect(budgetSummary).toContain("本次检查 1 项已授权资料")
  expect(budgetSummary).toContain("最长约 2 分钟")
  expect(budgetSummary).not.toContain("tokens")
  expect(budgetSummary).not.toContain("fingerprint")
  expect(budgetSummary).not.toContain("member")
  expect(budget.get("details").text()).toContain("tokens")
  expect(budget.get("details").text()).toContain("独立复核连接指纹")
})


it("waits for a pending check before adopting an already checked trial", async () => {
  const trial = { id: "trial-a", label: "保留动机", status: "sealed", stale: false, revision_id: "revision-a", changes: [{ resource: { kind: "writing_draft", id: "draft-a" }, label: "正文", operation: "replace", before: "旧稿", after: "试改" }], check: { verdict: "passed" }, can_seal: true }
  let status = "running"
  localStorage.setItem("novel_creative_v2:local:project-a", JSON.stringify({ caseId: "case-a", goal: "保留动机" }))
  const api = {
    capabilities: vi.fn(async () => ({ enabled: true, recipes: [] })),
    cases: vi.fn(async () => ({ items: [] })),
    getCase: vi.fn(async () => ({ id: "case-a", goal: "保留动机", constraints: [], recipe: { id: "revision" }, grant: { resources: [] } })),
    runs: vi.fn(async () => ({ items: [{ id: "check-a", status }] })),
    run: vi.fn(async () => ({ id: "check-a", status })),
    workspaces: vi.fn(async () => ({ items: [trial] })),
    diff: vi.fn(async () => trial),
    seal: vi.fn(),
  }
  setBridgeOverrides({ api: { collaboration: api } })
  const wrapper = mount(CreativeExperiments, { props: { projectId: "project-a" }, global: { stubs: { CognitionPanel: true, CreativeTrialEditor: true } } })
  await flushPromises()
  await wrapper.get(".creative-trial-button").trigger("click")
  await flushPromises()
  const adopt = wrapper.findAll("button").find(button => button.text() === "采用这一版…")
  expect(adopt.element.disabled).toBe(true)
  await adopt.trigger("click")
  expect(api.seal).not.toHaveBeenCalled()

  status = "completed"
  await wrapper.get('[aria-label="查看一次调查"]').setValue("check-a")
  await wrapper.findAll("button").find(button => button.text() === "刷新").trigger("click")
  await flushPromises()
  expect(adopt.element.disabled).toBe(false)
})
