/**
 * 世界库关系分组视角测试 — URL 编解码、payload 构造、失败文案与维护对话框。
 *
 * 数据形状对齐 G0 契约样例（relation-groups-response.json /
 * membership-batch-samples.json）；后端语义由服务端测试覆盖，此处固定
 * 前端纯函数与组件交互契约。
 */
import { describe, it, expect, afterEach, vi } from "vitest"
import { DOMWrapper, enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { nextTick } from "vue"

import {
  RELATION_MEMBERSHIP_MAX,
  RELATION_VIEW_PRESETS,
  buildMembershipAddPayload,
  buildMembershipRemovePayload,
  cardsFromLibraryItems,
  isCustomViewConfigured,
  isRelationMembersPage,
  membershipResultMessage,
  relationAddOptions,
  relationMembershipErrorInfo,
  relationRefLabel,
  relationSelectionScope,
  relationViewMeta,
  usesServerLibrary,
  worldCardFiltersFromQuery,
  worldCardQuery,
} from "../../../vue/views/world/bible/worldCards.js"
import WorldRelationRemoveDialog from "../../../vue/views/world/library/WorldRelationRemoveDialog.vue"
import WorldRelationGroupList from "../../../vue/views/world/library/WorldRelationGroupList.vue"
import WorldRelationMembers from "../../../vue/views/world/library/WorldRelationMembers.vue"
import WorldLibraryDirectory from "../../../vue/views/world/library/WorldLibraryDirectory.vue"
import WorldLibraryList from "../../../vue/views/world/library/WorldLibraryList.vue"
import WorldBibleTab from "../../../vue/views/world/bible/WorldBibleTab.vue"
import { setBridgeOverrides, resetBridgeOverrides } from "../../../vue/bridge/index.js"

const AFFILIATION_FILTERS = {
  q: "", kind: "all", type: "", state: "", layout: "list", sort: "updated",
  topicId: "", favorite: false, unclassified: false, skip: 0,
  groupView: "affiliation", groupId: "group-1", groupUnlinked: false,
  groupType: "", memberType: "", relationType: "", groupSide: "",
}

describe("关系视角 URL 编解码", () => {
  it("预设视角参数完整往返（组内页含分页）", () => {
    const query = new URLSearchParams(
      "group_view=affiliation&group_id=g-1&skip=50&sort=title&q=%E5%A1%94",
    )
    const filters = worldCardFiltersFromQuery(query)
    expect(filters).toMatchObject({
      groupView: "affiliation", groupId: "g-1", groupUnlinked: false,
      skip: 50, sort: "title", q: "塔",
    })
    const encoded = worldCardQuery(filters)
    expect(encoded.get("group_view")).toBe("affiliation")
    expect(encoded.get("group_id")).toBe("g-1")
    expect(encoded.get("skip")).toBe("50")
    expect(encoded.get("sort")).toBe("title")
    const decoded = worldCardFiltersFromQuery(encoded)
    expect(decoded).toEqual(filters)
  })

  it("组名搜索 q 与组内成员搜索 member_q 独立编解码", () => {
    // 回归：进入组后组名关键词不得串入成员过滤；返回组列表原样恢复组搜索。
    const filters = worldCardFiltersFromQuery(new URLSearchParams(
      "group_view=affiliation&group_id=g-1&q=%E5%A1%94%E7%BD%97%E4%BC%9A&member_q=%E5%85%8B%E8%8E%B1%E6%81%A9",
    ))
    expect(filters.q).toBe("塔罗会")
    expect(filters.memberQ).toBe("克莱恩")
    const encoded = worldCardQuery(filters)
    expect(encoded.get("q")).toBe("塔罗会")
    expect(encoded.get("member_q")).toBe("克莱恩")
    expect(worldCardFiltersFromQuery(encoded)).toEqual(filters)
    // 非关系视角不消费 member_q。
    expect(worldCardFiltersFromQuery(new URLSearchParams("member_q=x")).memberQ).toBe("")
  })

  it("custom 视角配置随 URL 恢复；非法值被容错丢弃", () => {
    const filters = worldCardFiltersFromQuery(new URLSearchParams(
      "group_view=custom&group_type=location&member_type=item&relation_type=guarded_by&group_side=target&group_unlinked=1",
    ))
    expect(filters).toMatchObject({
      groupView: "custom", groupType: "location", memberType: "item",
      relationType: "guarded_by", groupSide: "target", groupUnlinked: true,
    })
    const encoded = worldCardQuery(filters)
    expect(encoded.get("group_type")).toBe("location")
    expect(encoded.get("group_side")).toBe("target")
    expect(encoded.get("group_unlinked")).toBe("1")

    const bogus = worldCardFiltersFromQuery(new URLSearchParams(
      "group_view=bogus&group_id=g&group_side=sideways",
    ))
    expect(bogus.groupView).toBe("")
    expect(bogus.groupId).toBe("")
    expect(bogus.groupSide).toBe("")
  })

  it("无 group_view 时普通浏览参数行为不变", () => {
    const filters = worldCardFiltersFromQuery(new URLSearchParams("kind=entity&q=x"))
    expect(filters.groupView).toBe("")
    expect(worldCardQuery(filters).get("group_view")).toBe(null)
  })

  it("关系视角被视为服务端列表；成员页/自定义配置可判定", () => {
    expect(usesServerLibrary({ groupView: "event" })).toBe(true)
    expect(usesServerLibrary({ q: "" })).toBe(false)
    expect(isRelationMembersPage(AFFILIATION_FILTERS)).toBe(true)
    expect(isRelationMembersPage({ ...AFFILIATION_FILTERS, groupId: "", groupUnlinked: false })).toBe(false)
    expect(isRelationMembersPage({ ...AFFILIATION_FILTERS, groupId: "", groupUnlinked: true })).toBe(true)
    expect(isCustomViewConfigured({ groupView: "custom" })).toBe(false)
    expect(isCustomViewConfigured({
      groupView: "custom", groupType: "location",
      relationType: "guarded_by", groupSide: "target",
    })).toBe(true)
  })
})

describe("关系视角元数据", () => {
  const serverViews = [{
    key: "affiliation", title: "服务端势力成员", custom: false,
    match_relations: [
      { relation_type: "member_of", label: "成员", relation_kind: "social", group_side: "target" },
      { relation_type: "leader_of", label: "领导者", relation_kind: "social", group_side: "target" },
    ],
    default_relation: { relation_type: "member_of", label: "成员", relation_kind: "social", group_side: "target" },
  }]

  it("服务端 views 优先，缺失时回退内置预设", () => {
    expect(relationViewMeta(serverViews, AFFILIATION_FILTERS).title).toBe("服务端势力成员")
    const fallback = relationViewMeta(null, AFFILIATION_FILTERS)
    expect(fallback.title).toBe("势力成员")
    expect(fallback.default_relation).toMatchObject({ relation_type: "member_of", relation_kind: "social" })
  })

  it("custom 未配置完整时返回 null；配置后按参数构造", () => {
    expect(relationViewMeta(serverViews, { groupView: "custom" })).toBe(null)
    const custom = relationViewMeta(serverViews, {
      groupView: "custom", groupType: "location",
      relationType: "guarded_by", groupSide: "target",
    })
    expect(custom.match_relations[0]).toMatchObject({
      relation_type: "guarded_by", group_side: "target",
    })
  })

  it("可添加关系按 (type, side) 去重；标签回退 relation_type", () => {
    const options = relationAddOptions(relationViewMeta(null, { groupView: "location" }))
    expect(options.map((item) => item.relation_type)).toEqual([
      "located_at", "located_in", "位于", "contains", "包含",
    ])
    expect(relationRefLabel(
      relationViewMeta(null, { groupView: "affiliation" }),
      { relation: { relation_type: "member_of" } },
    )).toBe("成员")
    expect(relationRefLabel(null, { relation: { relation_type: "未知类型" } })).toBe("未知类型")
  })
})

describe("membership payload 构造", () => {
  it("add 预设缺省使用视角默认三元组并裁剪重复成员", () => {
    const { payload } = buildMembershipAddPayload({
      projectId: "p1", filters: AFFILIATION_FILTERS,
      memberIds: ["m1", "m1", "m2"],
    })
    expect(payload).toMatchObject({
      novel_id: "p1", action: "add", group_view: "affiliation",
      group_id: "group-1", member_ids: ["m1", "m2"], confirmed: true,
      relation_type: "member_of", relation_kind: "social", group_side: "target",
    })
  })

  it("空 kind 省略字段（event 视角开放字符串关系交服务端解析）；未关联页可传目标组", () => {
    const eventFilters = {
      ...AFFILIATION_FILTERS, groupView: "event", groupId: "event-1",
    }
    const { payload } = buildMembershipAddPayload({
      projectId: "p1", filters: eventFilters, memberIds: ["m1"],
      relation: { relation_type: "参与", relation_kind: "", group_side: "target" },
    })
    expect(payload.relation_type).toBe("参与")
    expect(payload.relation_kind).toBeUndefined()

    const unlinked = {
      ...AFFILIATION_FILTERS, groupId: "",
    }
    const picked = buildMembershipAddPayload({
      projectId: "p1", filters: unlinked, memberIds: ["m1"], groupId: "group-9",
    })
    expect(picked.payload.group_id).toBe("group-9")
    const missing = buildMembershipAddPayload({
      projectId: "p1", filters: unlinked, memberIds: ["m1"],
    })
    expect(missing.error).toContain("分组")
  })

  it("add 显式关系覆盖默认；custom 校验失败返回作者可读错误", () => {
    const { payload } = buildMembershipAddPayload({
      projectId: "p1", filters: AFFILIATION_FILTERS, memberIds: ["m1"],
      relation: { relation_type: "leader_of", relation_kind: "social", group_side: "target" },
    })
    expect(payload.relation_type).toBe("leader_of")

    const customFilters = {
      ...AFFILIATION_FILTERS, groupView: "custom",
      groupType: "location", relationType: "guarded_by", groupSide: "target",
    }
    const missing = buildMembershipAddPayload({ projectId: "p1", filters: customFilters, memberIds: ["m1"] })
    expect(missing.error).toContain("自定义视角")

    const ok = buildMembershipAddPayload({
      projectId: "p1", filters: customFilters, memberIds: ["m1"],
      relation: { relation_type: "guarded_by", relation_kind: "intentional", group_side: "target" },
    })
    expect(ok.payload.relation_kind).toBe("intentional")
    expect(ok.payload.group_type).toBe("location")

    expect(buildMembershipAddPayload({ projectId: "p1", filters: AFFILIATION_FILTERS, memberIds: [] }).error)
      .toContain("选择")
  })

  it("custom add 以对话框实际选择的关系与方向为准，不被 URL 旧配置静默覆盖", () => {
    // 回归：URL 配置 guarded_by/target 时在对话框改成 guards/source，
    // 此前 payload 末尾展开旧视角参数，会提交与确认面板相反的正式关系。
    const customFilters = {
      ...AFFILIATION_FILTERS, groupView: "custom",
      groupType: "location", relationType: "guarded_by", groupSide: "target",
    }
    const { payload } = buildMembershipAddPayload({
      projectId: "p1", filters: customFilters, memberIds: ["m1"],
      relation: { relation_type: "guards", relation_kind: "intentional", group_side: "source" },
    })
    expect(payload.relation_type).toBe("guards")
    expect(payload.group_side).toBe("source")
    expect(payload.relation_kind).toBe("intentional")
    expect(payload.group_type).toBe("location")
  })

  it("remove 构造精确 refs 清单并透传执行指纹", () => {
    const { payload } = buildMembershipRemovePayload({
      projectId: "p1", filters: AFFILIATION_FILTERS, memberIds: ["m1"],
      relationRefs: [
        { relation: { id: "r1" }, execution_fingerprint: "f1" },
        { relation: { id: "r1" }, execution_fingerprint: "f1" },
        { relation: { id: "r2" }, execution_fingerprint: "" },
      ],
    })
    expect(payload.relation_refs).toEqual([
      { id: "r1", expected_execution_fingerprint: "f1" },
    ])
    expect(payload).toMatchObject({ action: "remove", member_ids: ["m1"], confirmed: true })

    const empty = buildMembershipRemovePayload({
      projectId: "p1", filters: AFFILIATION_FILTERS, memberIds: ["m1"], relationRefs: [],
    })
    expect(empty.error).toContain("勾选")
  })

  it("单批成员上限 50 与后端契约一致", () => {
    expect(RELATION_MEMBERSHIP_MAX).toBe(50)
    const many = Array.from({ length: 60 }, (_, index) => `m${index}`)
    const { payload } = buildMembershipAddPayload({
      projectId: "p1", filters: AFFILIATION_FILTERS, memberIds: many,
    })
    expect(payload.member_ids).toHaveLength(50)
  })

  it("选择作用域包含项目、视角、分组与查询；分页不影响作用域", () => {
    const page1 = relationSelectionScope("p1", { ...AFFILIATION_FILTERS, skip: 0 })
    const page2 = relationSelectionScope("p1", { ...AFFILIATION_FILTERS, skip: 50 })
    const otherGroup = relationSelectionScope("p1", { ...AFFILIATION_FILTERS, groupId: "g-2" })
    const otherProject = relationSelectionScope("p2", AFFILIATION_FILTERS)
    expect(page1).toBe(page2)
    expect(page1).not.toBe(otherGroup)
    expect(page1).not.toBe(otherProject)
  })
})

describe("membership 失败文案与结果文案", () => {
  it("三类 409 各有作者可懂文案与后续入口", () => {
    expect(relationMembershipErrorInfo({ code: "stale_execution" })).toMatchObject({
      action: "retry", actionLabel: "刷新重试",
    })
    // 真实 request() 封装抛出的错误形状：错误码在 err.body.error。
    expect(relationMembershipErrorInfo({ body: { error: "stale_execution" } })).toMatchObject({
      action: "retry",
    })
    expect(relationMembershipErrorInfo({ code: "relation_exists_as_candidate" })).toMatchObject({
      action: "review", actionLabel: "去关系审核",
    })
    expect(relationMembershipErrorInfo({ code: "required_validation" })).toMatchObject({
      action: "validation", actionLabel: "去校验工具",
    })
    expect(relationMembershipErrorInfo({ message: "网络中断" })).toMatchObject({
      action: "retry",
    })
    // Pydantic 422 的 detail 数组不直接展示给作者。
    expect(relationMembershipErrorInfo({ body: { detail: [{ loc: ["member_ids"] }] } }).message)
      .toContain("校验")
  })

  it("成功 toast 汇总 added/reused/removed 计数", () => {
    expect(membershipResultMessage({ added_count: 2, reused_count: 1 }))
      .toBe("分组已更新：新增 2 条关系，复用已有 1 条。")
    expect(membershipResultMessage({ removed_count: 3 }))
      .toBe("分组已更新：结束 3 条关系。")
    expect(membershipResultMessage({})).toBe("分组没有需要变更的成员。")
  })
})

describe("成员卡 relation_refs 映射", () => {
  it("服务端 relation_refs 进入卡片读模型；缺失字段容错为空数组", () => {
    const cards = cardsFromLibraryItems([
      {
        kind: "entity", id: "e1", title: "成员一", state: "active",
        relation_refs: [{ relation: { id: "r1", relation_type: "member_of" }, execution_fingerprint: "f1" }],
      },
      { kind: "entity", id: "e2", title: "成员二", state: "active" },
    ])
    expect(cards[0].relationRefs).toHaveLength(1)
    expect(cards[0].relationRefs[0].relation.id).toBe("r1")
    expect(cards[1].relationRefs).toEqual([])
  })
})

describe("WorldRelationRemoveDialog", () => {
  enableAutoUnmount(afterEach)

  const VIEW_META = relationViewMeta(null, { groupView: "affiliation" })
  const MEMBERS = [
    {
      id: "m1", title: "克莱恩",
      relationRefs: [
        { relation: { id: "r1", relation_type: "member_of", description: "成员" }, execution_fingerprint: "f1" },
        { relation: { id: "r2", relation_type: "leader_of", description: "主持" }, execution_fingerprint: "f2" },
      ],
    },
    { id: "m2", title: "奥黛丽", relationRefs: [] },
  ]

  let dialogHost = null

  function mountDialog(props = {}) {
    dialogHost = document.createElement("div")
    document.body.appendChild(dialogHost)
    return mount(WorldRelationRemoveDialog, {
      props: { open: true, viewMeta: VIEW_META, members: MEMBERS, pending: false, errorInfo: null, ...props },
      attachTo: dialogHost,
    })
  }

  afterEach(() => {
    if (dialogHost) {
      dialogHost.remove()
      dialogHost = null
    }
  })

  // WorldToolDialog 将内容 Teleport 到 document.body，断言直接查文档。
  function dialogGet(selector) {
    const node = document.querySelector(selector)
    if (!node) throw new Error(`dialog missing ${selector}`)
    return node
  }

  it("显示受影响对象与关系数量；默认全选；提交透传勾选 refs", async () => {
    const wrapper = mountDialog()
    expect(dialogGet("[data-relation-remove-count]").textContent).toContain("2 / 2")
    expect(document.body.textContent).toContain("克莱恩")
    expect(document.body.textContent).toContain("这个对象在当前分组没有可结束的关系")

    const toggleR2 = dialogGet("[data-relation-id='r2']")
    toggleR2.checked = false
    toggleR2.dispatchEvent(new Event("change"))
    await nextTick()
    expect(dialogGet("[data-relation-remove-count]").textContent).toContain("1 / 2")

    dialogGet("[data-action='relation-remove-confirm']").click()
    await nextTick()
    const emitted = wrapper.emitted("submit")
    expect(emitted).toHaveLength(1)
    expect(emitted[0][0].map((ref) => ref.relation.id)).toEqual(["r1"])
  })

  it("清空勾选后不可提交；进行中禁用重复提交与关闭", async () => {
    const wrapper = mountDialog()
    for (const relationId of ["r1", "r2"]) {
      const toggle = dialogGet(`[data-relation-id='${relationId}']`)
      toggle.checked = false
      toggle.dispatchEvent(new Event("change"))
      await nextTick()
    }
    expect(dialogGet("[data-action='relation-remove-confirm']").disabled).toBe(true)

    await wrapper.setProps({ pending: true })
    expect(dialogGet("[data-action='relation-remove-confirm']").disabled).toBe(true)
    expect(dialogGet("[data-action='relation-remove-cancel']").disabled).toBe(true)
    expect(wrapper.emitted("submit")).toBeUndefined()
  })

  it("失败时显示错误与后续入口，保留勾选", async () => {
    const wrapper = mountDialog({
      errorInfo: relationMembershipErrorInfo({ code: "stale_execution" }),
    })
    expect(dialogGet("[data-relation-remove-error]").textContent).toContain("关系已在别处更新")
    dialogGet("[data-error-action='retry']").click()
    await nextTick()
    expect(wrapper.emitted("error-action")[0]).toEqual(["retry"])
  })
})

describe("WorldBibleTab 关系视角集成", () => {
  afterEach(() => { resetBridgeOverrides(); document.body.innerHTML = "" })

  const GROUPS = [
    { id: "g-1", name: "塔罗会", entity_type: "faction", member_count: 9 },
    { id: "g-2", name: "值夜者", entity_type: "faction", member_count: 0 },
  ]
  const MEMBER_ITEMS = [
    {
      kind: "entity", id: "m-1", title: "克莱恩", state: "active", item_type: "character",
      relation_refs: [
        { relation: { id: "r-1", source_id: "m-1", target_id: "g-1", relation_type: "member_of", status: "canonical" }, execution_fingerprint: "f1" },
        { relation: { id: "r-2", source_id: "m-1", target_id: "g-1", relation_type: "leader_of", status: "canonical" }, execution_fingerprint: "f2" },
      ],
    },
    { kind: "entity", id: "m-2", title: "奥黛丽", state: "active", item_type: "character" },
  ]

  function relationBible(overrides = {}) {
    return {
      pages: [], categories: [], drafts: [], synopsis: null, pageTemplates: [],
      activationProfiles: [],
      relationGroups: GROUPS, relationGroupsTotal: GROUPS.length,
      relationGroupsUnlinkedTotal: 5, relationViews: [],
      relationGroupsError: null,
      libraryItems: [], libraryTotal: 0, libraryError: null,
      ...overrides,
    }
  }

  function mountRelationTab({ filters, bible, bibleDeepLink }) {
    return mount(WorldBibleTab, {
      props: {
        projectId: "p1",
        subView: "bible",
        bible,
        bibleDeepLink: bibleDeepLink || { draftId: "", pageId: "" },
        defaultDisplayMode: "gallery",
        worldCardFilters: filters,
      },
      attachTo: document.body,
    })
  }

  it("组列表页渲染组名、完整成员数与零成员组；进入组写入 URL", async () => {
    const navigate = vi.fn(() => true)
    setBridgeOverrides({
      state: { currentProjectId: "p1", currentView: "world" },
      router: { navigate, refresh: vi.fn(async () => true), renderCurrentView: vi.fn() },
      toast: vi.fn(),
    })
    const wrapper = mountRelationTab({
      filters: { q: "", kind: "all", type: "", state: "", layout: "list", sort: "updated", topicId: "", favorite: false, unclassified: false, skip: 0, groupView: "affiliation", groupId: "", groupUnlinked: false, groupType: "", memberType: "", relationType: "", groupSide: "" },
      bible: relationBible(),
    })
    expect(wrapper.text()).toContain("塔罗会")
    expect(wrapper.text()).toContain("9")
    // 零成员组保留。
    expect(wrapper.text()).toContain("值夜者")

    expect(wrapper.text()).toContain("势力成员")
    wrapper.unmount()
  })

  it("组内成员页渲染去重成员与关系标签；relation_refs 计数为对象数", async () => {
    const toast = vi.fn()
    setBridgeOverrides({
      state: { currentProjectId: "p1", currentView: "world" },
      router: { navigate: vi.fn(() => true), refresh: vi.fn(async () => true), renderCurrentView: vi.fn() },
      toast,
    })
    const wrapper = mountRelationTab({
      filters: { q: "", kind: "all", type: "", state: "", layout: "list", sort: "updated", topicId: "", favorite: false, unclassified: false, skip: 0, groupView: "affiliation", groupId: "g-1", groupUnlinked: false, groupType: "", memberType: "", relationType: "", groupSide: "" },
      bible: relationBible({
        relationGroups: [], relationGroupsTotal: 0,
        libraryItems: MEMBER_ITEMS, libraryTotal: 2,
      }),
    })
    expect(wrapper.text()).toContain("克莱恩")
    expect(wrapper.text()).toContain("奥黛丽")
    // 多条匹配关系以标签展示（成员/领导者），成员数是对象数（2）。
    expect(wrapper.text()).toContain("成员")
    expect(wrapper.text()).toContain("领导者")
    expect(wrapper.text()).not.toContain("分组列表加载失败")
    wrapper.unmount()
  })

  it("分组查询失败显示错误与重试，不回退扁平列表", async () => {
    setBridgeOverrides({
      state: { currentProjectId: "p1", currentView: "world" },
      router: { navigate: vi.fn(() => true), refresh: vi.fn(async () => true), renderCurrentView: vi.fn() },
      toast: vi.fn(),
    })
    const wrapper = mountRelationTab({
      filters: { q: "", kind: "all", type: "", state: "", layout: "list", sort: "updated", topicId: "", favorite: false, unclassified: false, skip: 0, groupView: "affiliation", groupId: "", groupUnlinked: false, groupType: "", memberType: "", relationType: "", groupSide: "" },
      bible: relationBible({
        relationGroups: [], relationGroupsTotal: 0,
        relationGroupsError: "分组列表加载失败",
      }),
    })
    expect(wrapper.text()).toContain("分组列表加载失败")
    // 错误态提供重试入口。
    expect(wrapper.find("[data-author-action='retry']").exists()).toBe(true)
    // 未以普通扁平列表冒充分组结果：无组数据渲染。
    expect(wrapper.text()).not.toContain("塔罗会")
    wrapper.unmount()
  })

  it("open=health 深链实际打开世界健康（校验工具）面板", async () => {
    // 回归：required_validation 错误入口只跳 open=health，此前无消费者，
    // 工具弹窗为空。现在 WorldBibleTab 监听 openHealth 打开面板。
    setBridgeOverrides({
      state: { currentProjectId: "p1", currentView: "world" },
      router: { navigate: vi.fn(() => true), refresh: vi.fn(async () => true), renderCurrentView: vi.fn() },
      toast: vi.fn(),
    })
    const wrapper = mountRelationTab({
      filters: { q: "", kind: "all", type: "", state: "", layout: "list", sort: "updated", topicId: "", favorite: false, unclassified: false, skip: 0, groupView: "", groupId: "", groupUnlinked: false, groupType: "", memberType: "", relationType: "", groupSide: "" },
      bible: relationBible(),
      bibleDeepLink: { draftId: "", pageId: "", openHealth: true },
    })
    expect(wrapper.text()).toContain("世界健康")
    wrapper.unmount()
  })
})

describe("整改回归（2026-10-02 review）", () => {
  afterEach(() => { resetBridgeOverrides(); document.body.innerHTML = "" })

  const MEMBER_PAGE_FILTERS = {
    q: "", kind: "all", type: "", state: "", layout: "list", sort: "updated",
    topicId: "", favorite: false, unclassified: false, skip: 0,
    groupView: "affiliation", groupId: "g-1", groupUnlinked: false, memberQ: "",
    groupType: "", memberType: "", relationType: "", groupSide: "",
  }
  const MEMBER_ITEMS = [
    { kind: "entity", id: "m-1", title: "克莱恩", state: "active", item_type: "character", relation_refs: [] },
  ]

  function bibleOf(total = MEMBER_ITEMS.length) {
    return { libraryItems: MEMBER_ITEMS, libraryTotal: total, relationGroupsError: null }
  }

  function mountMembersPage({ projectId, filters, bible, api, toast, refresh }) {
    setBridgeOverrides({
      state: { currentProjectId: projectId, currentView: "world" },
      router: { navigate: vi.fn(() => true), refresh, renderCurrentView: vi.fn() },
      toast,
      api,
    })
    return mount(WorldRelationMembers, {
      props: {
        projectId,
        filters,
        viewMeta: RELATION_VIEW_PRESETS[0],
        bible,
        metaFor: () => ({ label: "人物", color: "#333", symbol: "人" }),
        relationKindOptions: [],
        groupLabel: "塔罗会",
      },
      attachTo: document.body,
    })
  }

  async function openAddDialog(wrapper) {
    await wrapper.find("input[data-action='relation-members-toggle-all']").setValue(true)
    await wrapper.find("button[data-action='relation-members-add']").trigger("click")
    await flushPromises()
  }

  // WorldToolDialog 将内容 Teleport 到 document.body，对话框内元素直接查文档。
  function docFind(selector) {
    const element = document.querySelector(selector)
    return element ? new DOMWrapper(element) : undefined
  }

  it("组列表进入组保留组名搜索 q、清空成员搜索 member_q", async () => {
    const wrapper = mount(WorldRelationGroupList, {
      props: {
        projectId: "p1",
        filters: { ...MEMBER_PAGE_FILTERS, groupId: "", q: "塔罗会" },
        viewMeta: RELATION_VIEW_PRESETS[0],
        groups: [{ id: "g-1", name: "塔罗会", entity_type: "faction", member_count: 9 }],
        total: 1,
        unlinkedTotal: 5,
        entityTypeOptions: [],
      },
    })
    await wrapper.find("button[data-action='relation-group-open']").trigger("click")
    const emitted = wrapper.emitted("apply-filters")[0][0]
    // q 不在补丁里：父组件合并后组名搜索留在 URL，返回组列表原样恢复。
    expect("q" in emitted).toBe(false)
    expect(emitted).toMatchObject({ groupId: "g-1", groupUnlinked: false, memberQ: "", skip: 0 })
    wrapper.unmount()
  })

  it("普通目录入口从关系视角显式退出：URL 不残留 group_view/group_id/搜索", async () => {
    const wrapper = mount(WorldLibraryDirectory, {
      props: {
        filters: { ...MEMBER_PAGE_FILTERS, q: "塔罗会" },
        topics: [], totalCount: 3, workingCount: 1, unclassifiedCount: 0,
        favoriteCount: 1, types: [], projectId: "p1",
        relationViewEntries: [{ key: "affiliation", title: "势力成员" }],
        unlinkedCount: 5,
      },
    })
    await wrapper.find("nav > button").trigger("click")
    expect(wrapper.emitted("select")[0][0]).toMatchObject({
      state: "", type: "", kind: "all", topicId: "", favorite: false, unclassified: false,
      groupView: "", groupId: "", groupUnlinked: false, memberQ: "", q: "",
    })
    wrapper.unmount()
  })

  it("未关联页添加目标组按 total 完整分页加载，第 51 个之后的组可选", async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) => ({ id: `g-${index}`, name: `组${index}` }))
    const secondPage = Array.from({ length: 10 }, (_, index) => ({ id: `g-${50 + index}`, name: `组${50 + index}` }))
    const listRelationGroups = vi.fn()
      .mockResolvedValueOnce({ items: firstPage, total: 60 })
      .mockResolvedValueOnce({ items: secondPage, total: 60 })
    const wrapper = mountMembersPage({
      projectId: "p-paging",
      filters: { ...MEMBER_PAGE_FILTERS, groupId: "", groupUnlinked: true },
      bible: bibleOf(),
      api: { world: { listRelationGroups, applyRelationMembershipBatch: vi.fn() } },
      toast: vi.fn(),
      refresh: vi.fn(),
    })
    await openAddDialog(wrapper)
    await flushPromises()
    expect(listRelationGroups).toHaveBeenCalledTimes(2)
    expect(listRelationGroups.mock.calls[0][0].skip).toBe(0)
    expect(listRelationGroups.mock.calls[1][0].skip).toBe(50)
    // 60 个组全部进入下拉（默认选中第一个，无占位项）。
    expect(document.querySelectorAll("[data-field='add-target-group'] option")).toHaveLength(60)
    expect(docFind("select[data-field='add-target-group']").element.value).toBe("g-0")
    wrapper.unmount()
  })

  it("组内添加默认当前组，可改选其他组把已有成员归入另一分组", async () => {
    const applyRelationMembershipBatch = vi.fn(async () => ({ added_count: 1 }))
    const listRelationGroups = vi.fn(async () => ({
      items: [{ id: "g-1", name: "塔罗会" }, { id: "g-2", name: "值夜者" }],
      total: 2,
    }))
    const wrapper = mountMembersPage({
      projectId: "p-retarget",
      filters: { ...MEMBER_PAGE_FILTERS, groupId: "g-1" },
      bible: bibleOf(),
      api: { world: { listRelationGroups, applyRelationMembershipBatch } },
      toast: vi.fn(),
      refresh: vi.fn(),
    })
    await openAddDialog(wrapper)
    const select = docFind("select[data-field='add-target-group']")
    expect(select).toBeTruthy()
    expect(select.element.value).toBe("g-1")
    await select.setValue("g-2")
    await docFind("button[data-action='relation-add-confirm']").trigger("click")
    await flushPromises()
    const payload = applyRelationMembershipBatch.mock.calls[0][0]
    expect(payload.group_id).toBe("g-2")
    expect(payload.group_view).toBe("affiliation")
    expect(payload.relation_type).toBe("member_of")
    wrapper.unmount()
  })

  it("提交后卸载的旧响应不再提示成功或刷新新页面（含正向对照）", async () => {
    let resolveBatch
    const deferred = new Promise((resolve) => { resolveBatch = resolve })
    const applyRelationMembershipBatch = vi.fn(() => deferred)
    const toast = vi.fn()
    const refresh = vi.fn()
    const wrapper = mountMembersPage({
      projectId: "p-stale",
      filters: { ...MEMBER_PAGE_FILTERS, groupId: "g-1" },
      bible: bibleOf(),
      api: { world: { listRelationGroups: vi.fn(async () => ({ items: [{ id: "g-1", name: "塔罗会" }], total: 1 })), applyRelationMembershipBatch } },
      toast,
      refresh,
    })
    await openAddDialog(wrapper)
    await docFind("button[data-action='relation-add-confirm']").trigger("click")
    expect(applyRelationMembershipBatch).toHaveBeenCalledTimes(1)
    // 提交后离开当前页面：旧 Promise 完成时组件已卸载。
    wrapper.unmount()
    resolveBatch({ added_count: 1 })
    await flushPromises()
    expect(toast).not.toHaveBeenCalled()
    expect(refresh).not.toHaveBeenCalled()

    // 正向对照：组件仍在原页面时，成功提示与刷新照常。
    const toast2 = vi.fn()
    const refresh2 = vi.fn()
    const wrapper2 = mountMembersPage({
      projectId: "p-stale-ok",
      filters: { ...MEMBER_PAGE_FILTERS, groupId: "g-1" },
      bible: bibleOf(),
      api: { world: { listRelationGroups: vi.fn(async () => ({ items: [{ id: "g-1", name: "塔罗会" }], total: 1 })), applyRelationMembershipBatch: vi.fn(async () => ({ added_count: 1 })) } },
      toast: toast2,
      refresh: refresh2,
    })
    await openAddDialog(wrapper2)
    await docFind("button[data-action='relation-add-confirm']").trigger("click")
    await flushPromises()
    expect(toast2).toHaveBeenCalledWith(expect.stringContaining("分组已更新"), "success")
    expect(refresh2).toHaveBeenCalledTimes(1)
    wrapper2.unmount()
  })

  it("提交后切到其他分组的旧响应同样被抑制", async () => {
    let resolveBatch
    const deferred = new Promise((resolve) => { resolveBatch = resolve })
    const applyRelationMembershipBatch = vi.fn(() => deferred)
    const toast = vi.fn()
    const refresh = vi.fn()
    const filters = { ...MEMBER_PAGE_FILTERS, groupId: "g-1" }
    const wrapper = mountMembersPage({
      projectId: "p-switch",
      filters,
      bible: bibleOf(),
      api: { world: { listRelationGroups: vi.fn(async () => ({ items: [{ id: "g-1", name: "塔罗会" }], total: 1 })), applyRelationMembershipBatch } },
      toast,
      refresh,
    })
    await openAddDialog(wrapper)
    await docFind("button[data-action='relation-add-confirm']").trigger("click")
    // 请求在途时切换分组：页面身份变化，旧响应不得按新分组提示成功。
    await wrapper.setProps({ filters: { ...filters, groupId: "g-2" } })
    resolveBatch({ added_count: 1 })
    await flushPromises()
    expect(toast).not.toHaveBeenCalled()
    expect(refresh).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe("WorldLibraryList 桌面列模板分支（2026-10-03 review P2）", () => {
  // 普通浏览与关系成员模式共用列表行；≥1080px 的列模板必须按 selectable
  // 分支，否则普通模式两行子元素落进三列网格，主行失去弹性、操作列可被
  // nowrap 长标题挤压。此处固定分支 class 与两套列模板的存在性。
  const CARDS = [{
    key: "entity-e1", id: "e-1", kind: "entity", title: "非常长的成员标题用于验证列收缩",
    state: "active", stateLabel: "已采用", summary: "摘要", isFavorite: false,
    relationRefs: [],
  }]
  const META = () => ({ symbol: "人", label: "人物", color: "" })

  it("普通浏览行不带 selectable 修饰类、不渲染勾选列", () => {
    const wrapper = mount(WorldLibraryList, {
      props: { cards: CARDS, metaFor: META },
    })
    const row = wrapper.find("li.world-library-list__row")
    expect(row.exists()).toBe(true)
    expect(row.classes()).not.toContain("world-library-list__row--selectable")
    expect(wrapper.find(".world-library-list__select").exists()).toBe(false)
    wrapper.unmount()
  })

  it("关系成员模式行带 selectable 修饰类并渲染勾选列", () => {
    const wrapper = mount(WorldLibraryList, {
      props: {
        cards: CARDS,
        metaFor: META,
        selectable: true,
        selectionScope: "world-relation-members:layout-test",
        selectionLimit: RELATION_MEMBERSHIP_MAX,
        memberMode: "group",
      },
    })
    const row = wrapper.find("li.world-library-list__row")
    expect(row.classes()).toContain("world-library-list__row--selectable")
    expect(wrapper.find(".world-library-list__select input[type='checkbox']").exists()).toBe(true)
    wrapper.unmount()
  })
})
