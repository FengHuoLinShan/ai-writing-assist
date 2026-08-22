/**
 * useWorldReview 测试 — 候选分组/动作可见性/证据模型/批量复核/决策模态。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"

vi.mock("../../../../shared/referencePicker.js", () => ({
  createReferencePicker: vi.fn(() => ({ destroy: vi.fn(), resolve: vi.fn() })),
}))

import {
  acceptAliasReviewItem,
  acceptRecommendedRelation,
  applyAliasReviewBatch,
  applyRelationReviewBatch,
  candidateActionLabel,
  candidateActionVisibility,
  changeReviewPage,
  groupSimilarNameCandidates,
  inlineEvidencePairs,
  reviewEvidenceSummary,
  recommendedRelationDecision,
  reviewTypeLabel,
  runReviewBulkAction,
  showAliasReviewEditForm,
  showAliasReviewDecisionForm,
  showRelationGroupReviewForm,
  showRelationReviewEditForm,
  splitCandidateGroups,
  syncReviewRegistry,
} from "../../../vue/views/world/logic/useWorldReview.js"
import { resetWorldSession, worldSession } from "../../../vue/views/world/worldSession.js"
import { getBulkSelection, toggleBulkSelection } from "../../../vue/views/world/logic/worldBulkSelection.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

let navigateMock
let toastMock
let confirmCalls
let modalCalls
let apiMock
let routerMock

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  resetWorldSession()
  navigateMock = vi.fn()
  toastMock = vi.fn()
  confirmCalls = []
  modalCalls = []
  document.body.innerHTML = ""
  apiMock = {
    world: {
      editAlias: vi.fn(async () => ({})),
      reviewEditRelationship: vi.fn(async () => ({})),
      reviewAliasesBatch: vi.fn(async () => ({ results: [] })),
      reviewRelationsBatch: vi.fn(async () => ({ results: [] })),
    },
  }
  routerMock = { navigate: navigateMock, refresh: vi.fn(async () => true), replace: vi.fn(async () => true) }
  setBridgeOverrides({
    api: apiMock,
    state: { currentProjectId: "p-rev", currentView: "world" },
    router: routerMock,
    toast: toastMock,
    showModalHtml: (title, html, buttons, options) => modalCalls.push({ title, html, buttons, options }),
    confirmAction: (message, onConfirm, confirmText) => confirmCalls.push({ message, onConfirm, confirmText }),
  })
  syncReviewRegistry({
    aliases: [],
    relationGroups: [],
    relations: [],
    reviewTypeCatalog: {
      alias_kinds: [{ value: "name", label: "名称", description: "名称变化" }],
      alias_types: [{ value: "name", label: "名称", default_kind: "name" }],
      relation_kinds: [{ value: "social", label: "社会/组织", description: "社会联系" }],
      relation_types: [{ value: "friend_of", label: "朋友", default_kind: "social" }],
    },
  })
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("相似名称分组", () => {
  it("同类型且名称相似归组（≥3 字包含 / bigram ≥0.72）", () => {
    const groups = groupSimilarNameCandidates([
      { name: "沉钟港", entity_type: "location" },
      { name: "沉钟港旧址", entity_type: "location" },
      { name: "雾岭", entity_type: "location" },
      { name: "月廷", entity_type: "organization" },
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0].map((item) => item.name)).toEqual(["沉钟港", "沉钟港旧址"])
  })

  it("类型不同不归组", () => {
    const groups = groupSimilarNameCandidates([
      { name: "沉钟港", entity_type: "location" },
      { name: "沉钟港", entity_type: "organization" },
    ])
    expect(groups).toHaveLength(0)
  })
})

describe("splitCandidateGroups / 动作标签与可见性", () => {
  it("定向别名候选与普通候选拆分", () => {
    const targeted = {
      id: "c1", name: "旧港", entity_type: "location",
      suggested_action: "alias_of_existing",
      suggested_existing_entity_id: "e1", suggested_existing_entity_name: "沉钟港",
    }
    const regular = { id: "c2", name: "雾岭", entity_type: "location", suggested_action: "create_new" }
    const split = splitCandidateGroups([targeted, regular])
    expect(split.targetedAliasCandidates).toHaveLength(1)
    expect(split.regularCandidates.map((item) => item.id)).toEqual(["c2"])
  })

  it("动作标签：已解析目标 → 作为X别名；未解析 → 疑似关联", () => {
    expect(candidateActionLabel({
      suggested_action: "alias_of_existing",
      suggested_existing_entity_id: "e1",
      suggested_existing_entity_name: "沉钟港",
    }).label).toBe("作为沉钟港别名")
    expect(candidateActionLabel({
      id: "c9",
      suggested_action: "link_to_existing",
      suggested_existing_entity_name: "雾岭",
    }).label).toBe("疑似关联雾岭（目标未解析）")
    expect(candidateActionLabel({ suggested_action: "create_new" }).label).toBe("创建新对象")
  })

  it("动作可见性：merge_with_existing 不显示采用、显示合并", () => {
    const vis = candidateActionVisibility({ suggested_action: "merge_with_existing" })
    expect(vis.canAccept).toBe(false)
    expect(vis.canMerge).toBe(true)
    const vis2 = candidateActionVisibility({ suggested_action: "create_new" })
    expect(vis2.canAccept).toBe(true)
    expect(vis2.canAlias).toBe(false)
  })
})

describe("证据模型", () => {
  it("inlineEvidencePairs 过滤空值", () => {
    const pairs = inlineEvidencePairs({ source: "deep_import", scene_index: 3, quote: "旧塔倒塌" })
    expect(pairs).toContainEqual(["来源", "深度导入"])
    expect(pairs).toContainEqual(["场景", 3])
    expect(pairs.find(([label]) => label === "处理批次")).toBeUndefined()
  })

  it("reviewEvidenceSummary 含诊断 JSON", () => {
    const evidence = reviewEvidenceSummary({ source: "manual", confidence: 0.9, workflow_id: "wf-1" }, "alias", 0.9)
    expect(evidence.summary).toContain("置信度 90%")
    expect(JSON.parse(evidence.diagnostic).workflow_id).toBe("wf-1")
  })

  it("reviewTypeLabel 命中目录", () => {
    expect(reviewTypeLabel("relation", "friend_of")).toBe("朋友")
    expect(reviewTypeLabel("alias", "unknown_type")).toBe("自定义详细类型")
  })
})

describe("changeReviewPage", () => {
  it("候选分页 navigate candidateQuery；越界不动", () => {
    changeReviewPage("candidates", 1, { skip: 0, limit: 20 }, 50)
    expect(navigateMock).toHaveBeenCalledWith("world", "review", true, expect.objectContaining({
      get: expect.any(Function),
    }))
    const query = navigateMock.mock.calls[0][3]
    expect(query.get("page")).toBe("2")
    expect(query.get("kind")).toBe("objects")

    navigateMock.mockClear()
    changeReviewPage("candidates", -1, { skip: 0, limit: 20 }, 50)
    expect(navigateMock).not.toHaveBeenCalled()
  })
})

describe("决策模态", () => {
  it.each([
    [
      "别名",
      () => {
        syncReviewRegistry({ aliases: [{ entity_id: "e1", alias: "旧港", alias_type: "name" }] })
        showAliasReviewEditForm("e1", "旧港")
      },
      () => { document.getElementById("alias-target-id").value = "" },
      "editAlias",
    ],
    [
      "关系",
      () => {
        syncReviewRegistry({ relations: [{
          id: "r1",
          source_id: "e1",
          target_id: "e2",
          relation_kind: "social", relation_type: "friend_of",
        }] })
        showRelationReviewEditForm("r1")
      },
      () => { document.getElementById("rel-review-type").value = "" },
      "reviewEditRelationship",
    ],
  ])("编辑后采用%s的本地校验失败时返回 false 且不调接口", async (_label, openForm, invalidate, apiMethod) => {
    openForm()
    document.body.innerHTML = modalCalls[0].html
    invalidate()

    await expect(modalCalls[0].buttons[0].handler()).resolves.toBe(false)
    expect(apiMock.world[apiMethod]).not.toHaveBeenCalled()
  })

  it.each([
    ["别名", "editAlias", () => {
      syncReviewRegistry({ aliases: [{ entity_id: "e1", alias: "旧港", alias_type: "name" }] })
      showAliasReviewEditForm("e1", "旧港")
    }],
    ["关系", "reviewEditRelationship", () => {
      syncReviewRegistry({ relations: [{
        id: "r1",
        source_id: "e1",
        target_id: "e2",
        relation_kind: "social", relation_type: "friend_of",
      }] })
      showRelationReviewEditForm("r1")
    }],
  ])("编辑后采用%s的 API 失败时返回 false 供原位重试", async (_label, apiMethod, openForm) => {
    apiMock.world[apiMethod].mockRejectedValueOnce(new Error("请求失败"))
    openForm()
    document.body.innerHTML = modalCalls[0].html

    await expect(modalCalls[0].buttons[0].handler()).resolves.toBe(false)
    expect(apiMock.world[apiMethod]).toHaveBeenCalledTimes(1)
    expect(toastMock).toHaveBeenCalledWith("请求失败", "error")
  })

  it("showAliasReviewDecisionForm 直接提交单条决定并清草稿", async () => {
    syncReviewRegistry({
      aliases: [{ entity_id: "e1", alias: "旧港", alias_kind: "name", alias_type: "name", confidence: 0.8 }],
      reviewTypeCatalog: {
        alias_kinds: [{ value: "name", label: "名称", description: "名称变化" }],
        alias_types: [{ value: "name", label: "名称", default_kind: "name" }],
      },
    })
    worldSession.aliasReviewErrors["e1::旧港"] = "旧错误"
    showAliasReviewDecisionForm("e1", "旧港")
    expect(modalCalls).toHaveLength(1)
    expect(modalCalls[0].title).toBe("处理别名")
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("alias-target-id").value = "e1"
    document.getElementById("alias-edit-text").value = "旧港"
    document.getElementById("alias-edit-type").value = "name"
    await modalCalls[0].buttons[0].handler()
    expect(apiMock.world.reviewAliasesBatch).toHaveBeenCalledWith(expect.objectContaining({
      decisions: [expect.objectContaining({ action: "accept", target_entity_id: "e1", alias: "旧港" })],
    }), "p-rev")
    expect(worldSession.aliasReviewDrafts["e1::旧港"]).toBeUndefined()
    expect(worldSession.aliasReviewErrors["e1::旧港"]).toBeUndefined()
    expect(routerMock.refresh).toHaveBeenCalled()
  })

  it("指纹变化时保留别名输入并要求重新核对", () => {
    sessionStorage.setItem("novel_world_review_draft:p-rev:alias:e1::旧港", JSON.stringify({
      expected_execution_fingerprint: "old",
      target_entity_id: "e1",
      alias: "旧港湾",
      alias_type: "name",
    }))
    syncReviewRegistry({ aliases: [{ entity_id: "e1", alias: "旧港", alias_type: "name", execution_fingerprint: "new" }] })

    showAliasReviewDecisionForm("e1", "旧港")

    expect(modalCalls[0].html).toContain("旧港湾")
    expect(worldSession.aliasReviewErrors["e1::旧港"]).toContain("内容已变化")
  })

  it("关系预览把对象名和描述作为纯文本", () => {
    const payload = '<img data-review-payload src="x" onerror="alert(1)">'
    setBridgeOverrides({
      showModalHtml: (title, html, buttons, options) => {
        modalCalls.push({ title, html, buttons, options })
        document.body.innerHTML = html
      },
    })
    syncReviewRegistry({
      relationGroups: [{
        group_id: "group-xss",
        source_id: "source-1",
        source_name: payload,
        target_id: "target-1",
        target_name: "目标对象",
        execution_fingerprint: "fp-xss",
        members: [{
          id: "relation-1",
          source_id: "source-1",
          target_id: "target-1",
          relation_kind: "social", relation_type: "friend_of",
          description: payload,
          strength: 0.5,
        }],
        canonical_relations: [],
      }],
      reviewTypeCatalog: {
        relation_types: [{ value: "friend_of", label: "朋友" }],
      },
    })

    showRelationGroupReviewForm("group-xss")

    const preview = document.getElementById("relation-review-preview")
    expect(preview?.querySelector("[data-review-payload]")).toBeNull()
    expect(preview?.textContent).toContain(payload)
  })

  it("关系对象搜索只允许最新响应更新选择", async () => {
    const untrustedName = '<img data-review-search-payload src="x" onerror="alert(1)">'
    let resolveOlder
    let resolveLatest
    const olderResponse = new Promise((resolve) => { resolveOlder = resolve })
    const latestResponse = new Promise((resolve) => { resolveLatest = resolve })
    apiMock.world.listEntities = vi.fn()
      .mockReturnValueOnce(olderResponse)
      .mockReturnValueOnce(latestResponse)
    setBridgeOverrides({
      showModalHtml: (title, html, buttons, options) => {
        modalCalls.push({ title, html, buttons, options })
        document.body.innerHTML = html
      },
    })
    syncReviewRegistry({
      relationGroups: [{
        group_id: "group-search",
        source_id: "e-source",
        source_name: "原始源对象",
        target_id: "e-target",
        target_name: "原始目标对象",
        execution_fingerprint: "fp-search",
        members: [{
          id: "relation-search",
          source_id: "e-source",
          target_id: "e-target",
          relation_kind: "social", relation_type: "friend_of",
          strength: 0.5,
        }],
        canonical_relations: [],
      }],
    })

    showRelationGroupReviewForm("group-search")
    const input = document.getElementById("relation-source-query")
    const button = document.getElementById("relation-source-search")
    const select = document.getElementById("relation-source-select")
    Object.defineProperty(select, "innerHTML", { set: () => { throw new Error("HTML sink used") } })

    input.value = "旧查询"
    const olderSearch = button.onclick()
    input.value = "新查询"
    const latestSearch = button.onclick()
    resolveLatest({ items: [{ id: "e-new", name: untrustedName, entity_type: "character", status: "canonical" }] })
    await latestSearch
    select.value = "e-new"

    resolveOlder({ items: [{ id: "e-old", name: "旧源对象", entity_type: "character", status: "canonical" }] })
    await olderSearch

    expect(Array.from(select.options, (option) => option.value)).toContain("e-new")
    expect(Array.from(select.options, (option) => option.value)).not.toContain("e-old")
    expect(select.value).toBe("e-new")
    expect(select.querySelector("[data-review-search-payload]")).toBeNull()
    expect(select.selectedOptions[0].textContent).toContain(untrustedName)
    await modalCalls[0].buttons[0].handler()
    expect(apiMock.world.reviewRelationsBatch.mock.calls[0][0].decisions[0].source_id).toBe("e-new")
    expect(routerMock.refresh).toHaveBeenCalled()
  })

  it("accept_separately 按后端契约提交每条关系与未选处置", async () => {
    setBridgeOverrides({
      showModalHtml: (title, html, buttons, options) => {
        modalCalls.push({ title, html, buttons, options })
        document.body.innerHTML = html
      },
    })
    syncReviewRegistry({ relationGroups: [{
      group_id: "g-separate", source_id: "e1", source_name: "林澈", target_id: "e2", target_name: "沉钟港",
      execution_fingerprint: "f".repeat(64), canonical_relations: [], members: [
        { id: "r1", relation_kind: "social", relation_type: "friend_of", description: "相识", strength: 0.6 },
        { id: "r2", relation_kind: "social", relation_type: "ally_of", description: "合作", strength: 0.8 },
      ],
    }] })
    showRelationGroupReviewForm("g-separate")
    document.getElementById("relation-review-action").value = "accept_separately"
    document.querySelectorAll('input[name="relation-review-member"]').forEach((input) => { input.checked = true })
    document.getElementById("relation-unselected-action").value = "keep_pending"

    await modalCalls[0].buttons[0].handler()

    const decision = apiMock.world.reviewRelationsBatch.mock.calls[0][0].decisions[0]
    expect(decision).toMatchObject({ action: "accept_separately", unselected_action: "keep_pending" })
    expect(decision.separate_relations).toEqual([
      expect.objectContaining({ candidate_relation_id: "r1", source_id: "e1", target_id: "e2", relation_type: "friend_of" }),
      expect.objectContaining({ candidate_relation_id: "r2", source_id: "e1", target_id: "e2", relation_type: "ally_of" }),
    ])
    expect(decision.primary_relation_id).toBeUndefined()
  })
})

describe("批量复核", () => {
  it("缺少别名分类时阻断直接采用并提示先分类", async () => {
    const item = { entity_id: "e1", alias: "旧港", alias_type: "name", execution_fingerprint: "fp" }
    await expect(acceptAliasReviewItem(item)).resolves.toBe(false)
    expect(apiMock.world.reviewAliasesBatch).not.toHaveBeenCalled()
    expect(toastMock).toHaveBeenCalledWith("请先选择别名分类", "warning")
  })

  it("缺少关系分类时阻断推荐采用", () => {
    const group = {
      group_id: "g-missing-kind", source_id: "e1", target_id: "e2", execution_fingerprint: "fp",
      members: [{ id: "r1", relation_type: "friend_of", strength: 0.5 }],
    }
    expect(acceptRecommendedRelation(group)).toBe(false)
    expect(apiMock.world.reviewRelationsBatch).not.toHaveBeenCalled()
    expect(toastMock).toHaveBeenCalledWith("请先选择关系分类", "warning")
  })

  it.each(["merge", "accept_separately"])("缺少关系分类时阻断已准备的 %s 决策", (action) => {
    const group = { group_id: `g-${action}`, execution_fingerprint: "fp", members: [{ id: "r1" }, { id: "r2" }] }
    worldSession.relationReviewDrafts[group.group_id] = action === "merge"
      ? { action, member_relation_ids: ["r1", "r2"], relation_type: "friend_of" }
      : { action, member_relation_ids: ["r1", "r2"], separate_relations: [{ candidate_relation_id: "r1", relation_type: "friend_of" }] }
    applyRelationReviewBatch([group])
    expect(confirmCalls).toHaveLength(0)
    expect(toastMock).toHaveBeenCalledWith("所选关系决策中有待分类项，请先选择关系分类", "warning")
  })

  it("决策栏可直接采用当前别名", async () => {
    const item = { entity_id: "e1", entity_name: "沉钟港", alias: "旧港", alias_kind: "name", alias_type: "name", execution_fingerprint: "f".repeat(64) }
    await acceptAliasReviewItem(item)
    expect(apiMock.world.reviewAliasesBatch.mock.calls[0][0].decisions[0]).toMatchObject({
      action: "accept", entity_id: "e1", target_entity_id: "e1", alias: "旧港", alias_kind: "name", alias_type: "name",
    })
    expect(routerMock.refresh).toHaveBeenCalled()
  })

  it("单条忽略别名后留下结果回执", async () => {
    const item = { entity_id: "e1", entity_name: "沉钟港", alias: "旧港", execution_fingerprint: "f".repeat(64) }
    apiMock.world.reviewAliasesBatch.mockResolvedValueOnce({
      results: [{ client_decision_id: "alias-0-e1", status: "success" }],
      succeeded_count: 1,
    })
    applyAliasReviewBatch([item], "ignore")
    await confirmCalls[0].onConfirm()
    expect(apiMock.world.reviewAliasesBatch.mock.calls[0][0].decisions[0]).toMatchObject({ action: "ignore", original_alias: "旧港" })
    expect(worldSession.reviewReceipt).toMatchObject({ targetKey: "e1::旧港", title: "别名已完成" })
  })

  it("决策栏按建议合并同类证据并保留未选项", async () => {
    const group = {
      group_id: "g1", source_id: "e1", target_id: "e2", execution_fingerprint: "f".repeat(64),
      members: [
        { id: "r1", relation_kind: "social", relation_type: "friend_of", suggested_relation_type: "friend_of", description: "证据一", strength: 0.7 },
        { id: "r2", relation_kind: "social", relation_type: "朋友", suggested_relation_type: "friend_of", description: "证据二", strength: 0.6 },
        { id: "r3", relation_kind: "social", relation_type: "enemy_of", description: "其他候选", strength: 0.8 },
      ],
    }
    expect(recommendedRelationDecision(group)).toMatchObject({
      action: "merge", member_relation_ids: ["r1", "r2"], unselected_action: "keep_pending", relation_type: "friend_of",
    })
    acceptRecommendedRelation(group)
    expect(confirmCalls[0].message).toContain("归并")
    await confirmCalls[0].onConfirm()
    expect(apiMock.world.reviewRelationsBatch.mock.calls[0][0].decisions[0]).toMatchObject({
      action: "merge", member_relation_ids: ["r1", "r2"], unselected_action: "keep_pending",
    })
  })

  it("决策栏并入已有正式关系前保留二次确认", async () => {
    const group = {
      group_id: "g-reuse", source_id: "e1", target_id: "e2", execution_fingerprint: "f".repeat(64),
      canonical_relations: [{ id: "canonical-1", source_id: "e1", target_id: "e2", relation_type: "friend_of" }],
      members: [{ id: "r1", relation_kind: "social", relation_type: "friend_of", description: "新证据", strength: 0.7 }],
    }

    acceptRecommendedRelation(group)

    expect(confirmCalls).toHaveLength(1)
    expect(confirmCalls[0].message).toContain("已有正式关系")
    expect(apiMock.world.reviewRelationsBatch).not.toHaveBeenCalled()
    await confirmCalls[0].onConfirm()
    expect(apiMock.world.reviewRelationsBatch).toHaveBeenCalledTimes(1)
  })

  it("别名批量：决策合成 + 成功清草稿与选择", async () => {
    const members = [
      { entity_id: "e1", alias: "旧港", alias_kind: "name", alias_type: "name", execution_fingerprint: "fp1" },
      { entity_id: "e1", alias: "老港", alias_kind: "name", alias_type: "nickname", execution_fingerprint: "fp2" },
    ]
    syncReviewRegistry({ aliases: members })
    worldSession.aliasReviewDrafts["e1::旧港"] = { target_entity_id: "e1", alias: "旧港", alias_kind: "name", alias_type: "name" }
    toggleBulkSelection("world-aliases", "e1::旧港", true)
    apiMock.world.reviewAliasesBatch = vi.fn(async () => ({
      results: [
        { client_decision_id: "alias-0-e1", status: "success" },
        { client_decision_id: "alias-1-e1", status: "stale", message: "指纹过期" },
      ],
      succeeded_count: 1,
      stale_count: 1,
    }))
    applyAliasReviewBatch(members, "accept")
    expect(confirmCalls).toHaveLength(1)
    await confirmCalls[0].onConfirm()
    const payload = apiMock.world.reviewAliasesBatch.mock.calls[0][0]
    expect(payload.confirmed).toBe(true)
    expect(payload.decisions).toHaveLength(2)
    expect(payload.decisions[0]).toMatchObject({
      client_decision_id: "alias-0-e1",
      action: "accept",
      entity_id: "e1",
      original_alias: "旧港",
      expected_execution_fingerprint: "fp1",
      target_entity_id: "e1",
    })
    expect(worldSession.aliasReviewDrafts["e1::旧港"]).toBeUndefined()
    expect(getBulkSelection("world-aliases").has("e1::旧港")).toBe(false)
    expect(worldSession.aliasReviewErrors["e1::老港"]).toContain("已过期")
  })

  it("关系批量：未准备决策时 toast 拦截", () => {
    const groups = [{ group_id: "g1", members: [{ id: "r1" }] }]
    syncReviewRegistry({ relationGroups: groups })
    applyRelationReviewBatch(groups, false)
    expect(toastMock).toHaveBeenCalledWith("所选关系组中仍有未准备决策的项目", "warning")
    expect(confirmCalls).toHaveLength(0)
  })

  it("关系整组忽略：无需草稿即可提交", async () => {
    const groups = [{ group_id: "g1", members: [{ id: "r1" }, { id: "r2" }], execution_fingerprint: "fpg" }]
    syncReviewRegistry({ relationGroups: groups })
    apiMock.world.reviewRelationsBatch = vi.fn(async () => ({
      results: [{ client_decision_id: "g1", status: "success" }],
      succeeded_count: 1,
    }))
    applyRelationReviewBatch(groups, true)
    expect(confirmCalls[0].confirmText).toBe("确认忽略")
    await confirmCalls[0].onConfirm()
    const payload = apiMock.world.reviewRelationsBatch.mock.calls[0][0]
    expect(payload.decisions[0]).toMatchObject({
      client_decision_id: "g1",
      action: "ignore",
      member_relation_ids: ["r1", "r2"],
    })
  })
})

describe("runReviewBulkAction 分派", () => {
  it("空选择 toast 警告", () => {
    runReviewBulkAction("world-aliases", "review-aliases-batch", [])
    expect(toastMock).toHaveBeenCalledWith("请先选择要处理的项目", "warning")
  })

  it("world-aliases 选中后走 applyAliasReviewBatch", () => {
    const members = [{ entity_id: "e1", alias: "旧港", alias_kind: "name", alias_type: "name", execution_fingerprint: "fp" }]
    syncReviewRegistry({ aliases: members })
    toggleBulkSelection("world-aliases", "e1::旧港", true)
    runReviewBulkAction("world-aliases", "review-aliases-batch", members)
    expect(confirmCalls).toHaveLength(1)
    expect(confirmCalls[0].message).toContain("确定采用所选 1 个别名")
  })
})
