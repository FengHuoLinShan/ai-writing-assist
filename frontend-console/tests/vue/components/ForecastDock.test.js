import { afterEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { reactive } from "vue"

const mocks = vi.hoisted(() => ({ subscription: null }))
vi.mock("../../../vue/composables/forecastStore.js", () => ({
  subscribeForecast: () => mocks.subscription,
}))

import ForecastDock from "../../../vue/components/ForecastDock.vue"

afterEach(() => {
  mocks.subscription = null
  vi.restoreAllMocks()
})

it("renders grounded performance cards and copies a readable option for writing", async () => {
  const option = {
    direction_id: "protect_first",
    motive: "protect",
    motive_reason: "先保护自己的不安",
    trigger: "如果对方继续追问",
    behavior: ["停顿", "把问题转回可核对的经过"],
    expression: "目光落向河面",
    body_language: "肩膀收紧",
    voice: { line: "你最后一次看见它是什么时候？", delivery: "轻声收住", subtext: "我还没有准备好解释" },
    psychology: "想确认线索",
    psychological_trigger: "对方追问失物意义",
    defense: "暂时不谈来历",
    notices: ["对方回避视线"],
    overlooks: ["没有注意到泥水"],
    change: { emotion: "略微集中", relationship: "信任未验证", goal: "核实目击时间" },
    basis: [{ kind: "author_condition", evidence_ids: ["source_0"], quote: "保持克制", note: "作者约束，不代表人物所知" }],
    assumptions: ["对话仍在继续"],
  }
  const item = {
    candidate_id: "candidate-1",
    issue_key: "issue-1",
    notice_version: 1,
    notice_status: "unread",
    run_id: "run-1",
    capability_id: "story.character_response.v2",
    assessment_hash: "a".repeat(64),
    context_hash: "b".repeat(64),
    title: "岑遥的本场表演候选",
    kind: "creative_opportunity",
    tier: "next",
    verification_status: "uncertain",
    freshness: "valid",
    statements: [{ basis: "proposed", text: "这些动作尚未发生。" }],
    why_now: "根据岑遥的角色可见资料，生成条件式候选。",
    directions: [],
    unknowns: ["没有已确认的人物时点状态"],
    evidence: [{ evidence_id: "source_0", resource_kind: "domain_result", resource_id: "resource-1", source_hash: "c".repeat(64), revision_token: "r1", label: "角色可见人物档案与本场状态" }],
    character_response: {
      schema_version: "character_response.v2",
      character_name: "岑遥",
      cutoff_label: "第 3 个场景截止点",
      options: [option],
      source_gaps: ["没有可用的人物时点状态"],
    },
    actions: [],
    basis_label: "基于当前保存版本",
    expires_at: "2026-11-15T00:00:00Z",
  }
  const state = reactive({
    projectId: "project-1",
    available: true,
    feed: { state: "ready", items: [item], coverage: {} },
    capabilities: [{ available: true }],
    focus: { scene_id: "scene-1" },
    loading: false,
    busy: false,
    stale: false,
    run: null,
    pending: null,
    pendingFeed: null,
    backupError: null,
    prepared: null,
    preparationRun: null,
    error: "",
    instruction: "",
    includeDeferred: false,
  })
  const forecast = {
    state,
    dirty: () => false,
    setInstruction: vi.fn(),
    decide: vi.fn(),
    prepare: vi.fn(),
    confirm: vi.fn(),
    cancel: vi.fn(),
    saveAutomatic: vi.fn(),
    acceptFeed: vi.fn(),
    more: vi.fn(),
    openDomain: vi.fn(),
    resume: vi.fn(),
    revisit: vi.fn(),
    refresh: vi.fn(),
    evaluate: vi.fn(),
    dispose: vi.fn(),
  }
  mocks.subscription = {
    forecast,
    update: vi.fn(),
    release: vi.fn(),
    activate: vi.fn(async () => true),
  }
  const writeText = vi.fn(async () => {})
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  })
  const toast = vi.fn()
  globalThis.toast = toast

  const wrapper = mount(ForecastDock, {
    props: { projectId: "project-1", context: { page: "scene", scene_id: "scene-1" } },
  })
  expect(wrapper.text()).toContain("以下动作均未发生")
  expect(wrapper.text()).toContain("角色可见人物档案")
  expect(wrapper.text()).toContain("保持克制")
  await wrapper.get("button[aria-label^='复制岑遥']").trigger("click")
  await flushPromises()
  expect(writeText).toHaveBeenCalledOnce()
  expect(writeText.mock.calls[0][0]).toContain("岑遥｜第 3 个场景截止点｜未发生的表演候选")
  expect(writeText.mock.calls[0][0]).toContain("声音：轻声收住")
  expect(writeText.mock.calls[0][0]).toContain("资料缺口：没有可用的人物时点状态")
  expect(toast).toHaveBeenCalledWith("已复制，可粘贴到写作输入中作为参考。", "success")
  wrapper.unmount()
})
