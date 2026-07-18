/**
 * WorldReviewTab 测试 — 三队列渲染契约、乐观更新、筛选导航、草稿徽标。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"

vi.mock("../../../../shared/referencePicker.js", () => ({
  createReferencePicker: vi.fn(() => ({ destroy: vi.fn(), resolve: vi.fn() })),
}))

import WorldReviewTab from "../../../vue/views/world/components/WorldReviewTab.vue"
import { resetWorldSession, worldSession } from "../../../vue/views/world/worldSession.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

let navigateMock
let toastMock
let confirmCalls

const CANDIDATES = [
  { id: "c1", name: "潮声会", entity_type: "organization", status: "candidate", suggested_action: "create_new", content_json: { _meta: { source: "deep_import" } } },
  {
    id: "c2", name: "旧灯塔", entity_type: "location", status: "candidate",
    suggested_action: "alias_of_existing",
    suggested_existing_entity_id: "e1", suggested_existing_entity_name: "沉钟港",
  },
]

const ALIAS_GROUPS = [
  {
    group_id: "ga1", entity_name: "沉钟港", member_count: 2,
    members: [
      { entity_id: "e1", alias: "旧港", alias_type: "name", confidence: 0.9, execution_fingerprint: "fp1" },
      { entity_id: "e1", alias: "老港", alias_type: "nickname", managed_by_suggestion: true },
    ],
  },
]

const RELATION_GROUPS = [
  {
    group_id: "g1", source_name: "林澈", target_name: "沉钟港", member_count: 1, evidence_count: 2,
    type_variants: ["friend_of"], scene_indices: [3], execution_fingerprint: "fpg",
    members: [{ id: "r1", relation_type: "friend_of", description: "驻守旧港", strength: 0.7 }],
  },
]

function mountTab(propOverrides = {}) {
  return mount(WorldReviewTab, {
    props: {
      projectId: "p-rev",
      reviewSubView: "review-objects",
      reviewCounts: { objects: 2, aliases: 2, relations: 1 },
      entityTypes: [{ value: "location", label: "地点" }, { value: "organization", label: "组织" }],
      candidates: CANDIDATES,
      candidateTotal: 2,
      aliasGroups: ALIAS_GROUPS,
      aliasGroupTotal: 1,
      aliasItemTotal: 2,
      relationGroups: RELATION_GROUPS,
      relationGroupTotal: 1,
      relationItemTotal: 1,
      ...propOverrides,
    },
  })
}

enableAutoUnmount(afterEach)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetWorldSession()
  navigateMock = vi.fn()
  toastMock = vi.fn()
  confirmCalls = []
  setBridgeOverrides({
    api: { world: { promoteEntity: vi.fn(async () => ({})) } },
    state: { currentProjectId: "p-rev", currentView: "world" },
    router: { navigate: navigateMock, refresh: vi.fn(async () => true), replace: vi.fn(async () => true) },
    toast: toastMock,
    showModalHtml: vi.fn(),
    confirmAction: (message, onConfirm, confirmText) => confirmCalls.push({ message, onConfirm, confirmText }),
  })
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("二级导航", () => {
  it("渲染计数徽标并 navigate", async () => {
    const wrapper = mountTab()
    expect(wrapper.find('[data-action="nav-review-objects"]').text()).toContain("对象 (2)")
    expect(wrapper.find('[data-action="nav-review-aliases"]').text()).toContain("别名 (2)")
    await wrapper.find('[data-action="nav-review-aliases"]').trigger("click")
    expect(navigateMock).toHaveBeenCalledWith("world", "review-aliases")
  })
})

describe("review-objects", () => {
  it("定向别名候选分组渲染，普通候选入表", () => {
    const wrapper = mountTab()
    const group = wrapper.find('.world-candidate-alias-group[data-target-id="e1"]')
    expect(group.exists()).toBe(true)
    expect(group.text()).toContain("沉钟港")
    const rows = wrapper.findAll("tbody tr[data-id]")
    expect(rows).toHaveLength(1)
    expect(rows[0].attributes("data-id")).toBe("c1")
  })

  it("候选行动作可见性（create_new：采用/编辑后采用/忽略）", () => {
    const wrapper = mountTab()
    const row = wrapper.find('tr[data-id="c1"]')
    expect(row.find('[data-action="accept-candidate"]').exists()).toBe(true)
    expect(row.find('[data-action="edit-entity"]').exists()).toBe(true)
    expect(row.find('[data-action="ignore-candidate"]').exists()).toBe(true)
    expect(row.find('[data-action="merge-entity"]').exists()).toBe(true) // allowMerge=true
    expect(row.find('[data-action="resolve-candidate-alias"]').exists()).toBe(true) // allowAlias=true
  })

  it("接受候选：乐观移除后 API 失败恢复快照", async () => {
    // API 挂起为 deferred：立即 reject 的 mock 会在微任务内走完「移除→失败→恢复」，
    // 等一拍检查时恢复已发生，无法观测到乐观移除态。
    let rejectPromote
    const api = { world: { promoteEntity: vi.fn(() => new Promise((_, reject) => { rejectPromote = reject })) } }
    setBridgeOverrides({
      api,
      state: { currentProjectId: "p-rev", currentView: "world" },
      router: { navigate: navigateMock, refresh: vi.fn(async () => true) },
      toast: toastMock,
      showModalHtml: vi.fn(),
      confirmAction: (message, onConfirm, confirmText) => confirmCalls.push({ message, onConfirm, confirmText }),
    })
    const wrapper = mountTab()
    await wrapper.find('tr[data-id="c1"] [data-action="accept-candidate"]').trigger("click")
    expect(confirmCalls).toHaveLength(1)
    const confirmPromise = confirmCalls[0].onConfirm()
    // API 仍挂起，乐观移除已落地
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(wrapper.find('tr[data-id="c1"]').exists()).toBe(false)
    rejectPromote(new Error("冲突"))
    await confirmPromise
    await wrapper.vm.$nextTick()
    // 失败后快照恢复
    expect(wrapper.find('tr[data-id="c1"]').exists()).toBe(true)
    expect(toastMock).toHaveBeenCalledWith("处理失败：冲突", "error")
  })

  it("错误态：candidateLoadError 渲染重试按钮", () => {
    const wrapper = mountTab({ candidates: [], candidateTotal: 0, candidateLoadError: "加载失败" })
    expect(wrapper.find('[data-action="retry-candidate-load"]').exists()).toBe(true)
  })

  it("筛选应用 navigate 写 query", async () => {
    const wrapper = mountTab()
    await wrapper.find("#review-candidate-source").setValue("deep_import")
    await wrapper.find('[data-action="apply-candidate-review-filters"]').trigger("click")
    const [view, subView, , query] = navigateMock.mock.calls[0]
    expect([view, subView]).toEqual(["world", "review-objects"])
    expect(query.get("source")).toBe("deep_import")
  })
})

describe("review-aliases", () => {
  it("组卡渲染：成员行、建议处理提示、编辑决策按钮", () => {
    const wrapper = mountTab({ reviewSubView: "review-aliases" })
    const card = wrapper.find('.review-group-card[data-group-id="ga1"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain("沉钟港")
    expect(card.text()).toContain("2 个待处理别名")
    const rows = card.findAll(".review-member-row")
    expect(rows).toHaveLength(2)
    expect(rows[0].find('[data-action="prepare-alias-review"]').exists()).toBe(true)
    expect(rows[1].text()).toContain("随对象建议处理")
    expect(rows[1].find('input[data-action="bulk-toggle-one"]').exists()).toBe(false)
  })

  it("草稿徽标与错误行", () => {
    worldSession.aliasReviewDrafts["e1::旧港"] = { target_entity_id: "e1", alias: "旧港", alias_type: "name" }
    worldSession.aliasReviewErrors["e1::旧港"] = "指纹过期"
    const wrapper = mountTab({ reviewSubView: "review-aliases" })
    const card = wrapper.find('.review-group-card[data-group-id="ga1"]')
    expect(card.find(".badge-canonical").text()).toBe("已编辑")
    expect(card.find(".review-item-error").text()).toBe("指纹过期")
  })
})

describe("review-relations", () => {
  it("组卡渲染：标题、计数、类型变体、成员", () => {
    const wrapper = mountTab({ reviewSubView: "review-relations" })
    const card = wrapper.find('.review-group-card[data-group-id="g1"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain("林澈 → 沉钟港")
    expect(card.text()).toContain("1 条候选 · 2 条证据")
    expect(card.text()).toContain("尚未准备决策")
    expect(card.find('[data-action="prepare-relation-review"]').text()).toBe("处理本组")
  })

  it("有草稿时徽标与按钮文案变化", () => {
    worldSession.relationReviewDrafts.g1 = { action: "merge", member_relation_ids: ["r1"] }
    const wrapper = mountTab({ reviewSubView: "review-relations" })
    const card = wrapper.find('.review-group-card[data-group-id="g1"]')
    expect(card.text()).toContain("已准备：归并")
    expect(card.find('[data-action="prepare-relation-review"]').text()).toBe("修改决策")
  })

  it("快捷筛选 navigate 写 query", async () => {
    const wrapper = mountTab({ reviewSubView: "review-relations" })
    await wrapper.find('[data-action="set-relation-quick-filter"][data-filter-key="multi_type_only"]').trigger("click")
    const [view, subView, , query] = navigateMock.mock.calls[0]
    expect([view, subView]).toEqual(["world", "review-relations"])
    expect(query.get("multi_type_only")).toBe("true")
  })
})
