/**
 * useWorldReview 测试 — 候选分组/动作可见性/证据模型/批量复核/决策模态。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"

vi.mock("../../../../shared/referencePicker.js", () => ({
  createReferencePicker: vi.fn(() => ({ destroy: vi.fn(), resolve: vi.fn() })),
}))

import {
  applyAliasReviewBatch,
  applyRelationReviewBatch,
  candidateActionLabel,
  candidateActionVisibility,
  changeReviewPage,
  groupSimilarNameCandidates,
  inlineEvidencePairs,
  reviewEvidenceSummary,
  reviewTypeLabel,
  runReviewBulkAction,
  showAliasReviewDecisionForm,
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

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetWorldSession()
  navigateMock = vi.fn()
  toastMock = vi.fn()
  confirmCalls = []
  modalCalls = []
  apiMock = {
    world: {
      reviewAliasesBatch: vi.fn(async () => ({ results: [] })),
      reviewRelationsBatch: vi.fn(async () => ({ results: [] })),
    },
  }
  setBridgeOverrides({
    api: apiMock,
    state: { currentProjectId: "p-rev", currentView: "world" },
    router: { navigate: navigateMock, refresh: vi.fn(async () => true), replace: vi.fn(async () => true) },
    toast: toastMock,
    showModalHtml: (title, html, buttons, options) => modalCalls.push({ title, html, buttons, options }),
    confirmAction: (message, onConfirm, confirmText) => confirmCalls.push({ message, onConfirm, confirmText }),
  })
  syncReviewRegistry({
    aliases: [],
    relationGroups: [],
    relations: [],
    reviewTypeCatalog: {
      alias_types: [{ value: "name", label: "名称" }],
      relation_types: [{ value: "friend_of", label: "朋友" }],
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
    expect(pairs).toContainEqual(["Scene", 3])
    expect(pairs.find(([label]) => label === "Workflow")).toBeUndefined()
  })

  it("reviewEvidenceSummary 含诊断 JSON", () => {
    const evidence = reviewEvidenceSummary({ source: "manual", confidence: 0.9, workflow_id: "wf-1" }, "alias", 0.9)
    expect(evidence.summary).toContain("置信度 90%")
    expect(JSON.parse(evidence.diagnostic).workflow_id).toBe("wf-1")
  })

  it("reviewTypeLabel 命中目录", () => {
    expect(reviewTypeLabel("relation", "friend_of")).toBe("朋友 (friend_of)")
    expect(reviewTypeLabel("alias", "unknown_type")).toBe("unknown_type")
  })
})

describe("changeReviewPage", () => {
  it("候选分页 navigate candidateQuery；越界不动", () => {
    changeReviewPage("candidates", 1, { skip: 0, limit: 20 }, 50)
    expect(navigateMock).toHaveBeenCalledWith("world", "review-objects", true, expect.objectContaining({
      get: expect.any(Function),
    }))
    const query = navigateMock.mock.calls[0][3]
    expect(query.get("page")).toBe("2")

    navigateMock.mockClear()
    changeReviewPage("candidates", -1, { skip: 0, limit: 20 }, 50)
    expect(navigateMock).not.toHaveBeenCalled()
  })
})

describe("决策模态", () => {
  it("showAliasReviewDecisionForm 保存草稿到 session 并清错误", async () => {
    syncReviewRegistry({
      aliases: [{ entity_id: "e1", alias: "旧港", alias_type: "name", confidence: 0.8 }],
      reviewTypeCatalog: { alias_types: [{ value: "name", label: "名称" }] },
    })
    worldSession.aliasReviewErrors["e1::旧港"] = "旧错误"
    showAliasReviewDecisionForm("e1", "旧港")
    expect(modalCalls).toHaveLength(1)
    expect(modalCalls[0].title).toBe("准备别名复核决策")
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("alias-target-id").value = "e1"
    document.getElementById("alias-edit-text").value = "旧港"
    document.getElementById("alias-edit-type").value = "name"
    await modalCalls[0].buttons[0].handler()
    expect(worldSession.aliasReviewDrafts["e1::旧港"]).toEqual({
      target_entity_id: "e1",
      alias: "旧港",
      alias_type: "name",
    })
    expect(worldSession.aliasReviewErrors["e1::旧港"]).toBeUndefined()
  })
})

describe("批量复核", () => {
  it("别名批量：决策合成 + 成功清草稿与选择", async () => {
    const members = [
      { entity_id: "e1", alias: "旧港", alias_type: "name", execution_fingerprint: "fp1" },
      { entity_id: "e1", alias: "老港", alias_type: "nickname", execution_fingerprint: "fp2" },
    ]
    syncReviewRegistry({ aliases: members })
    worldSession.aliasReviewDrafts["e1::旧港"] = { target_entity_id: "e1", alias: "旧港", alias_type: "name" }
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
    const members = [{ entity_id: "e1", alias: "旧港", execution_fingerprint: "fp" }]
    syncReviewRegistry({ aliases: members })
    toggleBulkSelection("world-aliases", "e1::旧港", true)
    runReviewBulkAction("world-aliases", "review-aliases-batch", members)
    expect(confirmCalls).toHaveLength(1)
    expect(confirmCalls[0].message).toContain("确定采用所选 1 个别名")
  })
})
