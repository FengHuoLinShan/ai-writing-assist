/**
 * WorldReviewTab 测试 — 三队列渲染契约、乐观更新、筛选导航、草稿徽标。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"

vi.mock("../../../../shared/referencePicker.js", () => ({
  createReferencePicker: vi.fn(() => ({ destroy: vi.fn(), resolve: vi.fn() })),
}))

import WorldReviewTab from "../../../vue/views/world/components/WorldReviewTab.vue"
import { resetWorldSession, worldSession } from "../../../vue/views/world/worldSession.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

let navigateMock
let toastMock
let confirmCalls
let apiMock
let showModalMock
let currentQuery
let commitQueryMock
let refreshMock

const CANDIDATES = [
  { id: "c1", name: "潮声会", entity_type: "organization", status: "candidate", suggested_action: "create_new", summary: "码头工人的互助行会", importance_level: "important", content_json: { _meta: { source: "deep_import" } } },
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
      { entity_id: "e1", alias: "旧港", alias_kind: "name", alias_type: "name", confidence: 0.9, execution_fingerprint: "fp1" },
      { entity_id: "e1", alias: "老港", alias_kind: "name", alias_type: "nickname", managed_by_suggestion: true },
    ],
  },
]

const RELATION_GROUPS = [
  {
    group_id: "g1", source_id: "e-source", source_name: "林澈", target_id: "e-target", target_name: "沉钟港", member_count: 1, evidence_count: 2,
    type_variants: ["friend_of"], scene_indices: [3], execution_fingerprint: "fpg",
    members: [{ id: "r1", relation_kind: "social", relation_type: "friend_of", description: "驻守旧港", strength: 0.7 }],
  },
]

function mountTab(propOverrides = {}) {
  return mount(WorldReviewTab, {
    props: {
      projectId: "p-rev",
      reviewSubView: "review-objects",
      reviewCounts: { objects: 2, aliases: 2, relations: 1 },
      entityTypes: [{ value: "location", label: "地点" }, { value: "organization", label: "组织" }],
      reviewTypeCatalog: {
        alias_kinds: [{ value: "name", label: "名称", description: "名称变化" }],
        alias_types: [{ value: "name", label: "名称", default_kind: "name" }, { value: "nickname", label: "昵称", default_kind: "name" }],
        relation_kinds: [{ value: "social", label: "社会/组织", description: "社会联系" }],
        relation_types: [{ value: "friend_of", label: "朋友", default_kind: "social" }, { value: "ally_of", label: "盟友", default_kind: "social" }],
      },
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
  currentQuery = new URLSearchParams()
  commitQueryMock = vi.fn((query) => {
    currentQuery = new URLSearchParams(query?.toString?.() || "")
    return true
  })
  refreshMock = vi.fn(async () => true)
  confirmCalls = []
  apiMock = {
    world: {
      promoteEntity: vi.fn(async () => ({})),
      getEntity: vi.fn(async (id) => ({ id, name: id === "e-source" ? "林澈" : "沉钟港", status: "canonical" })),
      reviewAliasesBatch: vi.fn(async () => ({ results: [] })),
      reviewRelationsBatch: vi.fn(async () => ({ results: [] })),
    },
  }
  showModalMock = vi.fn()
  setBridgeOverrides({
    api: apiMock,
    state: { currentProjectId: "p-rev", currentView: "world" },
    router: {
      navigate: navigateMock,
      refresh: refreshMock,
      replace: vi.fn(async () => true),
      getCurrentQuery: () => currentQuery,
      commitCurrentQuery: commitQueryMock,
    },
    toast: toastMock,
    showModalHtml: showModalMock,
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

  it("队列只保留一段状态说明，计数导航仍可用", async () => {
    const wrapper = mountTab()
    expect(wrapper.find('[data-author-action="needs_decision"]').exists()).toBe(false)
    expect(wrapper.get(".world-list-description").text()).toContain("尚未采用")
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

  it("对象队列只显示查看入口，决策区展示摘要和完整操作", async () => {
    const wrapper = mountTab()
    const row = wrapper.find('tr[data-id="c1"]')
    expect(row.text()).toContain("组织 · 重要设定")
    expect(row.text()).toContain("码头工人的互助行会")
    expect(row.findAll("button")).toHaveLength(1)
    await row.get('[data-action="prepare-candidate-review"]').trigger("click")
    const decision = wrapper.get(".world-review-decision")
    expect(decision.text()).toContain("决定是否采用“潮声会”")
    expect(decision.text()).toContain("码头工人的互助行会")
    expect(decision.find('[data-action="accept-candidate"]').exists()).toBe(true)
    expect(decision.find('[data-action="edit-entity"]').exists()).toBe(true)
    expect(decision.find('[data-action="ignore-candidate"]').exists()).toBe(true)
    expect(decision.find('[data-action="merge-entity"]').exists()).toBe(true)
    expect(decision.find('[data-action="resolve-candidate-alias"]').exists()).toBe(true)
    expect(decision.findAll(".btn-primary")).toHaveLength(1)
    expect(decision.get('[data-action="accept-candidate"]').classes()).toContain("btn-primary")
  })

  it("建议设为别名时只突出对应决策", async () => {
    const wrapper = mountTab()
    await wrapper.get('.world-candidate-alias-item[data-id="c2"] [data-action="prepare-candidate-review"]').trigger("click")
    const decision = wrapper.get(".world-review-decision")
    expect(decision.findAll(".btn-primary")).toHaveLength(1)
    expect(decision.get('[data-action="resolve-candidate-alias"]').classes()).toContain("btn-primary")
    expect(decision.find('[data-action="accept-candidate"]').exists()).toBe(false)
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
    await wrapper.find('tr[data-id="c1"] [data-action="prepare-candidate-review"]').trigger("click")
    await wrapper.find('.world-review-decision [data-action="accept-candidate"]').trigger("click")
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

  it("深链直接打开目标建议并可返回设定共创", async () => {
    currentQuery = new URLSearchParams("kind=objects&review_item=c1&return_to=world_ai&return_subview=bible")
    const wrapper = mountTab()
    expect(wrapper.get(".world-review-decision").text()).toContain("决定是否采用“潮声会”")
    expect(wrapper.get(".world-review-origin").text()).toContain("来自设定共创")
    await wrapper.get('[data-action="return-to-world-ai"]').trigger("click")
    const [view, subView, updateHistory, query] = navigateMock.mock.calls.at(-1)
    expect([view, subView, updateHistory]).toEqual(["world", "bible", true])
    expect(query.get("owner_ai")).toBe("1")
    expect(query.get("owner_ai_mode")).toBe("world")
  })

  it("已处理的深链给出明确去向而不是空白决策区", () => {
    currentQuery = new URLSearchParams("kind=objects&review_item=done&return_to=world_ai")
    const wrapper = mountTab({ candidates: [], candidateTotal: 0 })
    expect(wrapper.get(".world-review-queue .empty-state").text()).toContain("已不在待处理队列")
    expect(wrapper.find('[data-action="return-to-world-ai"]').exists()).toBe(true)
  })

  it("错误态：candidateLoadError 渲染重试按钮", () => {
    const wrapper = mountTab({ candidates: [], candidateTotal: 0, candidateLoadError: "加载失败" })
    expect(wrapper.find('[data-action="retry-candidate-load"]').exists()).toBe(true)
    expect(wrapper.get('[data-author-action="must_fix"]').text()).toContain("原有资料没有变化")
    expect(wrapper.find('[data-author-action="needs_decision"]').exists()).toBe(false)
  })

  it("空队列与其它世界资料空态保持文字优先", () => {
    const wrapper = mountTab({ candidates: [], candidateTotal: 0 })
    expect(wrapper.get(".world-review-queue .empty-state").text()).toContain("没有待处理对象")
    expect(wrapper.find(".empty-icon").exists()).toBe(false)
  })

  it("选中项被筛选或翻页移出后清空决策区", async () => {
    const wrapper = mountTab()
    await wrapper.get('tr[data-id="c1"]').trigger("click")
    expect(wrapper.get(".world-review-decision").text()).toContain("潮声会")
    await wrapper.setProps({ candidates: [CANDIDATES[1]], candidateTotal: 1 })
    expect(wrapper.get(".world-review-decision").text()).toContain("从左侧队列选择一项")
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

  it("快速筛选有可见分组名，批量栏直接出现在结果后", () => {
    const wrapper = mountTab()
    const quickFilters = wrapper.get('[role="group"][aria-labelledby="review-candidate-quick-label"]')
    expect(wrapper.get("#review-candidate-quick-label").text()).toBe("快速查看")
    expect(quickFilters.findAll("button")).toHaveLength(4)
    expect(wrapper.find(".world-review-batch").exists()).toBe(false)
    const summary = wrapper.get(".world-review-result-summary")
    const toolbar = wrapper.get('.bulk-toolbar[data-scope="world-candidates"]')
    expect(summary.element.compareDocumentPosition(toolbar.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(toolbar.get('[data-bulk-action="accept-candidates"]').attributes("disabled")).toBeDefined()
  })
})

describe("review-aliases", () => {
  it("高级筛选使用可访问名称并保持别名筛选值与选项语义", async () => {
    const wrapper = mountTab({
      reviewSubView: "review-aliases",
      aliasReviewFilters: {
        source: "deep_import", workflow_id: "workflow-7", scene_index: "3", source_chapter_index: "2",
        confidence_min: "0.85", confidence_max: "0.99", has_quote: "true",
        type_kind: "custom", alias_kind: "name", skip: 0, limit: 50,
      },
    })
    const controls = [
      ["#review-alias-scene", "按场景序号筛选待处理别名", "3"],
      ["#review-alias-chapter", "按章节序号筛选待处理别名", "2"],
      ["#review-alias-confidence-min", "待处理别名最低置信度", "0.85"],
      ["#review-alias-confidence-max", "待处理别名最高置信度", "0.99"],
      ["#review-alias-kind", "待处理别名分类", "name"],
      ["#review-alias-type-kind", "待处理别名详细类型范围", "custom"],
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
    expect(query.get("alias_kind")).toBe("name")
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
    expect(rows[0].find('[data-action="prepare-alias-review"]').text()).toBe("查看并决定")
    expect(rows[1].text()).toContain("随对象建议处理")
    expect(rows[1].find('input[data-action="bulk-toggle-one"]').exists()).toBe(false)
  })

  it("别名批量栏无需展开并保持零选择禁用", () => {
    const wrapper = mountTab({ reviewSubView: "review-aliases" })
    expect(wrapper.get("#review-alias-quick-label").text()).toBe("快速查看")
    expect(wrapper.find(".world-review-batch").exists()).toBe(false)
    const toolbar = wrapper.get('.bulk-toolbar[data-scope="world-aliases"]')
    expect(toolbar.text()).toContain("0别名已选")
    expect(toolbar.get('[data-bulk-action="review-aliases-batch"]').attributes("disabled")).toBeDefined()
  })

  it("单条别名在右侧决策区编辑并采用，不再打开弹窗", async () => {
    const wrapper = mountTab({ reviewSubView: "review-aliases" })
    await wrapper.get('[data-action="prepare-alias-review"]').trigger("click")

    const panel = wrapper.get(".world-alias-decision")
    expect(showModalMock).not.toHaveBeenCalled()
    expect(wrapper.get("#world-review-decision-title").text()).toBe("决定“旧港”的归属")
    expect(panel.text()).toContain("归属对象")
    expect(panel.text()).toContain("↑")
    expect(panel.text()).toContain("加入上方对象的别名")
    expect(panel.get('[data-action="confirm-alias-merge"]').text()).toBe("采用别名")
    expect(panel.get("#alias-inline-text").element.value).toBe("旧港")
    expect(panel.get("#alias-inline-kind").element.value).toBe("name")
    expect(panel.get("#alias-inline-type").element.value).toBe("name")

    await panel.get("#alias-inline-text").setValue("旧港湾")
    await panel.get('[data-action="confirm-alias-merge"]').trigger("click")
    expect(apiMock.world.reviewAliasesBatch).toHaveBeenCalledWith(expect.objectContaining({
      confirmed: true,
      decisions: [expect.objectContaining({
        action: "accept",
        entity_id: "e1",
        target_entity_id: "e1",
        alias: "旧港湾",
        alias_kind: "name",
        alias_type: "name",
      })],
    }), "p-rev")
  })

  it("取消返回队列但保留别名草稿", async () => {
    const wrapper = mountTab({ reviewSubView: "review-aliases" })
    await wrapper.get('[data-action="prepare-alias-review"]').trigger("click")
    await wrapper.get("#alias-inline-text").setValue("草稿别名")
    await wrapper.get('[data-action="cancel-alias-decision"]').trigger("click")

    expect(wrapper.find(".world-alias-decision").exists()).toBe(false)
    expect(worldSession.aliasReviewDrafts["e1::旧港"].alias).toBe("草稿别名")
  })

  it("选中项写入 URL，刷新后恢复决策位置，稍后决定时清除", async () => {
    currentQuery = new URLSearchParams({ kind: "aliases" })
    const wrapper = mountTab({ reviewSubView: "review-aliases" })
    await wrapper.get('[data-action="prepare-alias-review"]').trigger("click")
    expect(currentQuery.get("review_item")).toBe("e1::旧港")

    wrapper.unmount()
    const restored = mountTab({ reviewSubView: "review-aliases" })
    expect(restored.get("#world-review-decision-title").text()).toBe("决定“旧港”的归属")
    expect(restored.find(".world-alias-decision").exists()).toBe(true)

    await restored.get('[data-action="cancel-alias-decision"]').trigger("click")
    expect(currentQuery.get("review_item")).toBeNull()
  })

  it("别名加载失败提供用户语言、次级诊断与重试", async () => {
    const wrapper = mountTab({ reviewSubView: "review-aliases", aliasGroups: [], aliasItemTotal: 0, aliasReviewLoadError: "HTTP 503" })
    const error = wrapper.get('[data-author-action="must_fix"]')
    expect(error.attributes("role")).toBe("alert")
    expect(error.text()).toContain("原有资料没有变化")
    expect(error.get(".review-error-details").text()).toContain("HTTP 503")
    await error.get('[data-action="retry-alias-review-load"]').trigger("click")
    expect(refreshMock).toHaveBeenCalledTimes(1)
  })

  it("自定义详细类型可显示原值并显式采用类型建议", async () => {
    const groups = [{
      ...ALIAS_GROUPS[0],
      member_count: 1,
      members: [{
        ...ALIAS_GROUPS[0].members[0],
        alias_type: "别称",
        type_kind: "custom",
        suggested_alias_type: "nickname",
      }],
    }]
    const wrapper = mountTab({ reviewSubView: "review-aliases", aliasGroups: groups, aliasItemTotal: 1 })
    await wrapper.get('[data-action="prepare-alias-review"]').trigger("click")

    expect(wrapper.get("#alias-inline-type-custom").element.value).toBe("别称")
    await wrapper.get('[data-action="use-alias-type-suggestion"]').trigger("click")
    expect(wrapper.get("#alias-inline-type").element.value).toBe("nickname")
    expect(wrapper.find("#alias-inline-type-custom").exists()).toBe(false)
  })

  it("草稿徽标与错误行", () => {
    worldSession.aliasReviewDrafts["e1::旧港"] = { target_entity_id: "e1", alias: "旧港", alias_type: "name" }
    worldSession.aliasReviewErrors["e1::旧港"] = "指纹过期"
    const wrapper = mountTab({ reviewSubView: "review-aliases" })
    const card = wrapper.find('.review-group-card[data-group-id="ga1"]')
    expect(card.findAll(".badge-canonical").map((badge) => badge.text())).toContain("已编辑")
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

  it("关系批量栏与快速筛选使用同一层级", () => {
    const wrapper = mountTab({ reviewSubView: "review-relations" })
    expect(wrapper.get("#review-relation-quick-label").text()).toBe("快速查看")
    expect(wrapper.find(".world-review-batch").exists()).toBe(false)
    expect(wrapper.get('.bulk-toolbar[data-scope="world-relation-groups"]').text()).toContain("0关系组已选")
  })

  it("关系加载失败可重新加载，技术详情默认收起", async () => {
    const wrapper = mountTab({ reviewSubView: "review-relations", relationGroups: [], relationItemTotal: 0, relationReviewLoadError: "HTTP 504" })
    const error = wrapper.get('[data-author-action="must_fix"]')
    expect(error.attributes("role")).toBe("alert")
    expect(error.get(".review-error-details").attributes("open")).toBeUndefined()
    await error.get('[data-action="retry-relation-review-load"]').trigger("click")
    expect(refreshMock).toHaveBeenCalledTimes(1)
  })

  it("高级筛选使用可访问名称并保持关系筛选值与选项语义", async () => {
    const wrapper = mountTab({
      reviewSubView: "review-relations",
      relationReviewFilters: {
        relation_type: "friend_of", scene_index: "5", source_chapter_index: "4",
        strength_min: "0.7", strength_max: "0.9", has_quote: "false",
        type_kind: "recommended", relation_kind: "social", skip: 0, limit: 50,
      },
    })
    const controls = [
      ["#review-relation-kind", "按关系分类筛选待处理关系", "social"],
      ["#review-relation-type", "按详细类型筛选待处理关系", "friend_of"],
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
    expect(query.get("relation_kind")).toBe("social")
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
    expect(card.find('[data-action="prepare-relation-review"]').text()).toBe("查看并决定")
    await card.trigger("click")
    await flushPromises()
    expect(showModalMock).not.toHaveBeenCalled()
    expect(wrapper.get("#world-review-decision-title").text()).toBe("确定“林澈 → 沉钟港”的关系")
    expect(wrapper.findAll('[data-action="relation-person-card"]')).toHaveLength(2)
    expect(wrapper.get('[data-relation-slot="source"]').text()).toContain("拖入人物")
    expect(wrapper.get('[data-relation-slot="target"]').text()).toContain("拖入人物")
    expect(wrapper.get('[data-action="confirm-relation-decision"]').text()).toBe("采用关系")
  })

  it("拖动一张卡会自动完成两端配对并提交现有关系决策", async () => {
    const wrapper = mountTab({ reviewSubView: "review-relations" })
    const card = wrapper.find('.review-group-card[data-group-id="g1"]')
    await card.trigger("click")
    await flushPromises()

    let dragged = ""
    const dataTransfer = {
      effectAllowed: "",
      setData: vi.fn((_, value) => { dragged = value }),
      getData: vi.fn(() => dragged),
    }
    await wrapper.get('[data-person-id="e-target"]').trigger("dragstart", { dataTransfer })
    await wrapper.get('[data-relation-slot="source"]').trigger("drop", { dataTransfer })

    expect(wrapper.get('[data-relation-slot="source"]').text()).toContain("沉钟港")
    expect(wrapper.get('[data-relation-slot="target"]').text()).toContain("林澈")
    expect(worldSession.relationReviewDrafts.g1).toMatchObject({ source_id: "e-target", target_id: "e-source" })

    await wrapper.get('[data-action="confirm-relation-decision"]').trigger("click")
    expect(apiMock.world.reviewRelationsBatch).toHaveBeenCalledWith(expect.objectContaining({
      confirmed: true,
      decisions: [expect.objectContaining({
        action: "accept",
        source_id: "e-target",
        target_id: "e-source",
        relation_kind: "social",
        relation_type: "friend_of",
      })],
    }), "p-rev")
  })

  it("点击配对可替代拖放，取消后保留关系草稿", async () => {
    const wrapper = mountTab({ reviewSubView: "review-relations" })
    await wrapper.get('.review-group-card[data-group-id="g1"]').trigger("click")
    await flushPromises()
    await wrapper.get('[data-person-id="e-source"]').trigger("click")
    await wrapper.get('[data-relation-slot="target"]').trigger("click")
    await wrapper.get("#relation-inline-description").setValue("反向关系草稿")
    await wrapper.get('[data-action="cancel-relation-decision"]').trigger("click")

    expect(wrapper.find(".world-relation-decision").exists()).toBe(false)
    expect(worldSession.relationReviewDrafts.g1).toMatchObject({
      source_id: "e-target",
      target_id: "e-source",
      description: "反向关系草稿",
    })
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
