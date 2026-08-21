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
  sessionStorage.clear()
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
  it("全部概览按对象优先给出推荐下一项", async () => {
    const wrapper = mountTab({ reviewSubView: "review", reviewKind: "all" })
    expect(wrapper.findAll(".world-review-overview-card")).toHaveLength(3)
    expect(wrapper.get(".world-review-next").text()).toContain("对象")
    await wrapper.get('[data-action="open-recommended-review"]').trigger("click")
    expect(navigateMock.mock.calls[0].slice(0, 3)).toEqual(["world", "review", true])
    expect(navigateMock.mock.calls[0][3].get("kind")).toBe("objects")
  })

  it("渲染计数徽标并 navigate", async () => {
    const wrapper = mountTab()
    expect(wrapper.get('[data-author-action="needs_decision"]').text()).toContain("已采用、忽略或过期内容不计入当前待办")
    expect(wrapper.find('[data-action="nav-review-objects"]').element.tagName).toBe("BUTTON")
    expect(wrapper.find('[data-action="nav-review-objects"]').attributes("type")).toBe("button")
    expect(wrapper.find('[data-action="nav-review-objects"]').attributes("aria-current")).toBe("page")
    expect(wrapper.find('[data-action="nav-review-aliases"]').attributes("aria-current")).toBeUndefined()
    expect(wrapper.find('[data-action="nav-review-objects"]').text()).toContain("对象 (2)")
    expect(wrapper.find('[data-action="nav-review-aliases"]').text()).toContain("别名 (2)")
    await wrapper.find('[data-action="nav-review-aliases"]').trigger("click")
    expect(navigateMock).toHaveBeenCalledWith("world", "review", true, expect.any(URLSearchParams))
    expect(navigateMock.mock.calls[0][3].get("kind")).toBe("aliases")
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
    expect(wrapper.get('[data-author-action="must_fix"]').text()).toContain("必须修复")
    expect(wrapper.find('[data-author-action="needs_decision"]').exists()).toBe(false)
  })

  it("选中项被筛选或翻页移出后清空决策区", async () => {
    const wrapper = mountTab()
    await wrapper.get('tr[data-id="c1"]').trigger("click")
    expect(wrapper.get(".world-review-decision").text()).toContain("潮声会")
    await wrapper.setProps({ candidates: [CANDIDATES[1]], candidateTotal: 1 })
    expect(wrapper.get(".world-review-decision").text()).toContain("从左侧选择一项")
  })

  it("筛选应用 navigate 写 query", async () => {
    const wrapper = mountTab({ candidateFilters: { source: "deep_import", skip: 0, limit: 20 } })
    await wrapper.find("#review-candidate-q").setValue("港")
    await wrapper.find("#review-candidate-action").setValue("alias")
    await wrapper.find("#review-candidate-q").trigger("keyup.enter")
    const [view, subView, , query] = navigateMock.mock.calls.at(-1)
    expect([view, subView]).toEqual(["world", "review"])
    expect(query.get("kind")).toBe("objects")
    expect(query.get("q")).toBe("港")
    expect(query.get("suggested_action")).toBe("alias")
    expect(query.get("source")).toBe("deep_import")
  })

  it("搜索可单独清除，也可清除全部条件", async () => {
    const wrapper = mountTab({ candidateFilters: { q: "港", entity_type: "location", skip: 0, limit: 20 } })
    await wrapper.get('[data-action="clear-candidate-review-search"]').trigger("click")
    expect(navigateMock.mock.calls.at(-1)[3].get("q")).toBeNull()
    expect(navigateMock.mock.calls.at(-1)[3].get("entity_type")).toBe("location")
    await wrapper.get('.world-review-active-filters [data-action="reset-candidate-review-filters"]').trigger("click")
    expect(navigateMock.mock.calls.at(-1)[3].get("entity_type")).toBeNull()
  })

  it("对象任务标签互斥，再点当前标签可取消", async () => {
    const wrapper = mountTab({ candidateFilters: { suggested_action: "create_new", skip: 0, limit: 20 } })
    expect(wrapper.get('[data-action="set-candidate-task-filter"][data-filter-value="alias"]').text()).toBe("建议设为别名")
    const merge = wrapper.get('[data-action="set-candidate-task-filter"][data-filter-value="merge_with_existing"]')
    await merge.trigger("click")
    expect(navigateMock.mock.calls.at(-1)[3].get("suggested_action")).toBe("merge_with_existing")
    const active = wrapper.get('[data-action="set-candidate-task-filter"][data-filter-value="create_new"]')
    await active.trigger("click")
    expect(navigateMock.mock.calls.at(-1)[3].get("suggested_action")).toBeNull()
  })
})

describe("review-aliases", () => {
  it("高级筛选使用可访问名称并保持别名筛选值与选项语义", async () => {
    const wrapper = mountTab({
      reviewSubView: "review-aliases",
      aliasReviewFilters: {
        source: "deep_import", workflow_id: "workflow-7", scene_index: "3", source_chapter_index: "2",
        confidence_min: "0.85", confidence_max: "0.99", has_quote: "true",
        type_kind: "custom", skip: 0, limit: 50,
      },
    })
    const controls = [
      ["#review-alias-scene", "按场景序号筛选待处理别名", "3"],
      ["#review-alias-chapter", "按章节序号筛选待处理别名", "2"],
      ["#review-alias-confidence-min", "待处理别名最低置信度", "0.85"],
      ["#review-alias-confidence-max", "待处理别名最高置信度", "0.99"],
      ["#review-alias-type-kind", "待处理别名类型范围", "custom"],
      ["#review-alias-evidence", "待处理别名引用证据", "true"],
      ["#review-alias-page-size", "待处理别名每页数量", "50"],
    ]

    for (const [selector, label, value] of controls) {
      const control = wrapper.get(selector)
      expect(control.attributes("aria-label")).toBe(label)
      expect(control.element.value).toBe(value)
    }
    expect(wrapper.find("#review-alias-source").exists()).toBe(false)
    expect(wrapper.find("#review-alias-workflow").exists()).toBe(false)
    expect(wrapper.findAll("#review-alias-type-kind option").map((option) => option.element.value)).toEqual(["", "recommended", "custom"])
    expect(wrapper.findAll("#review-alias-page-size option").map((option) => option.element.value)).toEqual(["20", "50"])

    await wrapper.get("#review-alias-scene").setValue("8")
    await wrapper.get("#review-alias-evidence").setValue("false")
    await wrapper.get("#review-alias-page-size").setValue("20")
    const [view, subView, , query] = navigateMock.mock.calls.at(-1)
    expect([view, subView]).toEqual(["world", "review"])
    expect(query.get("kind")).toBe("aliases")
    expect(query.get("source")).toBe("deep_import")
    expect(query.get("type_kind")).toBe("custom")
    expect(query.get("scene_index")).toBe("8")
    expect(query.get("has_quote")).toBe("false")
    expect(query.get("limit")).toBeNull()
  })

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
  it("桌面为队列与决策区，窄屏有返回队列控件", () => {
    const wrapper = mountTab({ reviewSubView: "review-relations" })
    expect(wrapper.find(".world-review-workbench").exists()).toBe(true)
    expect(wrapper.find(".world-review-queue").exists()).toBe(true)
    expect(wrapper.find(".world-review-decision").exists()).toBe(true)
    expect(wrapper.get(".world-review-mobile-back").text()).toBe("返回队列")
  })

  it("高级筛选使用可访问名称并保持关系筛选值与选项语义", async () => {
    const wrapper = mountTab({
      reviewSubView: "review-relations",
      relationReviewFilters: {
        relation_type: "friend_of", scene_index: "5", source_chapter_index: "4",
        strength_min: "0.7", strength_max: "0.9", has_quote: "false",
        type_kind: "recommended", skip: 0, limit: 50,
      },
    })
    const controls = [
      ["#review-relation-type", "按关系类型筛选待处理关系", "friend_of"],
      ["#review-relation-scene", "按场景序号筛选待处理关系", "5"],
      ["#review-relation-source-chapter", "按章节序号筛选待处理关系", "4"],
      ["#review-relation-strength-min", "待处理关系最低强度", "0.7"],
      ["#review-relation-strength-max", "待处理关系最高强度", "0.9"],
      ["#review-relation-evidence", "待处理关系引用证据", "false"],
      ["#review-relation-page-size", "待处理关系每页数量", "50"],
    ]

    for (const [selector, label, value] of controls) {
      const control = wrapper.get(selector)
      expect(control.attributes("aria-label")).toBe(label)
      expect(control.element.value).toBe(value)
    }
    expect(wrapper.find("#review-relation-type-kind").exists()).toBe(false)
    expect(wrapper.findAll("#review-relation-page-size option").map((option) => option.element.value)).toEqual(["20", "50"])

    await wrapper.get("#review-relation-type").setValue("ally_of")
    await wrapper.get("#review-relation-evidence").setValue("true")
    await wrapper.get("#review-relation-page-size").setValue("20")
    const [view, subView, , query] = navigateMock.mock.calls.at(-1)
    expect([view, subView]).toEqual(["world", "review"])
    expect(query.get("kind")).toBe("relations")
    expect(query.get("relation_type")).toBe("ally_of")
    expect(query.get("has_quote")).toBe("true")
    expect(query.get("type_kind")).toBe("recommended")
    expect(query.get("limit")).toBeNull()
  })

  it("组卡渲染：标题、计数、类型变体、成员", async () => {
    const wrapper = mountTab({ reviewSubView: "review-relations" })
    const card = wrapper.find('.review-group-card[data-group-id="g1"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain("林澈 → 沉钟港")
    expect(card.text()).toContain("1 条候选 · 2 条证据")
    expect(card.text()).toContain("待处理")
    expect(card.find('[data-action="prepare-relation-review"]').text()).toBe("预览并处理")
    expect(wrapper.find('[data-action="accept-recommended-relation"]').exists()).toBe(false)
    await card.trigger("click")
    expect(wrapper.get('[data-action="accept-recommended-relation"]').text()).toBe("按此结果采用")
  })

  it("编辑草稿不再伪装成已处理状态", () => {
    worldSession.relationReviewDrafts.g1 = { action: "merge", member_relation_ids: ["r1"] }
    const wrapper = mountTab({ reviewSubView: "review-relations" })
    const card = wrapper.find('.review-group-card[data-group-id="g1"]')
    expect(card.text()).toContain("待处理")
    expect(card.find('[data-action="prepare-relation-review"]').text()).toBe("预览并处理")
  })

  it("快捷筛选 navigate 写 query", async () => {
    const wrapper = mountTab({ reviewSubView: "review-relations" })
    await wrapper.find('[data-action="set-relation-quick-filter"][data-filter-key="multi_type_only"]').trigger("click")
    const [view, subView, , query] = navigateMock.mock.calls[0]
    expect([view, subView]).toEqual(["world", "review"])
    expect(query.get("kind")).toBe("relations")
    expect(query.get("multi_type_only")).toBe("true")
  })

  it("关系任务标签可组合并携带反向/正式关系条件", async () => {
    const wrapper = mountTab({
      reviewSubView: "review-relations",
      relationReviewFilters: { multi_type_only: "true", skip: 0, limit: 20 },
    })
    await wrapper.get('[data-action="set-relation-quick-filter"][data-filter-key="has_reverse_candidates"]').trigger("click")
    const query = navigateMock.mock.calls.at(-1)[3]
    expect(query.get("multi_type_only")).toBe("true")
    expect(query.get("has_reverse_candidates")).toBe("true")
  })
})
