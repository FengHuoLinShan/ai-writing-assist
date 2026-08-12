/**
 * worldEntityOps 测试 — 模态表单与 API 语义（bridge 截获 showModalHtml/confirmAction）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"

vi.mock("../../../../shared/referencePicker.js", () => ({
  createReferencePicker: vi.fn(() => ({ destroy: vi.fn(), resolve: vi.fn() })),
}))

import {
  deleteEntity,
  editEntity,
  findEntity,
  ignoreCandidate,
  acceptCandidate,
  markEntityReviewed,
  promoteEntity,
  registerCandidateListHooks,
  runObjectsBulkAction,
  showEntityCreateForm,
  showEntityFusionSuggestions,
  showKnowledgeForm,
  showMergeForm,
  showResolveAliasForm,
  showRollbackForm,
  syncWorldListRegistry,
} from "../../../vue/views/world/logic/worldEntityOps.js"
import { clearBulkSelection, toggleBulkSelection } from "../../../vue/views/world/logic/worldBulkSelection.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const ENTITIES = [
  { id: "e1", name: "沉钟港", entity_type: "location", status: "canonical", summary: "旧港" },
  { id: "e2", name: "月廷", entity_type: "organization", status: "candidate", summary: "教团" },
  { id: "e3", name: "秦岚", entity_type: "character", status: "canonical", summary: "调查员" },
]
const CANDIDATES = [
  { id: "c1", name: "潮声会", entity_type: "organization", status: "candidate", suggested_action: "create_new" },
]

let modalCalls
let confirmCalls
let toastCalls
let apiMock

function captureModal(title, html, buttons, options) {
  modalCalls.push({ title, html, buttons, options })
}

function deferred() {
  let resolve
  const promise = new Promise((resolvePromise) => { resolve = resolvePromise })
  return { promise, resolve }
}

beforeEach(() => {
  modalCalls = []
  confirmCalls = []
  toastCalls = []
  document.body.innerHTML = ""
  vi.spyOn(window, "open").mockImplementation(() => null)
  apiMock = {
    world: {
      createEntity: vi.fn(async () => ({})),
      updateEntity: vi.fn(async () => ({})),
      promoteEntity: vi.fn(async () => ({})),
      deleteEntity: vi.fn(async () => ({})),
      getEntity: vi.fn(async () => null),
      resolveEntityAsAlias: vi.fn(async () => ({})),
      mergeEntity: vi.fn(async () => ({})),
      rollbackEntity: vi.fn(async () => ({ warnings: [] })),
      createKnowledge: vi.fn(async () => ({})),
      applyEntityFusionSuggestions: vi.fn(async () => ({ applied: 0 })),
      listKnowledge: vi.fn(async () => ({ items: [], total: 0 })),
      createKnowledge: vi.fn(async () => ({})),
      updateKnowledge: vi.fn(async () => ({})),
    },
  }
  setBridgeOverrides({
    api: apiMock,
    state: { currentProjectId: "p-ops", currentView: "world" },
    toast: (...args) => toastCalls.push(args),
    showModalHtml: captureModal,
    confirmAction: (message, onConfirm, confirmText, onCancel) => {
      confirmCalls.push({ message, confirmText, onConfirm, onCancel })
    },
    confirm: vi.fn(() => true),
    router: { refresh: vi.fn(async () => true) },
  })
  syncWorldListRegistry({ entities: ENTITIES, candidates: CANDIDATES, entityTypes: [{ value: "location", label: "地点" }, { value: "organization", label: "组织" }, { value: "character", label: "人物" }] })
  registerCandidateListHooks({})
  clearBulkSelection("world-objects")
})

afterEach(() => {
  vi.restoreAllMocks()
  resetBridgeOverrides()
})

describe("findEntity / 注册表", () => {
  it("entities 与 candidates 合并查找", () => {
    expect(findEntity("e1")?.name).toBe("沉钟港")
    expect(findEntity("c1")?.name).toBe("潮声会")
    expect(findEntity("nope")).toBeNull()
  })
})

describe("showEntityCreateForm", () => {
  it("打开新建模态并绑定类型控件；提交调 createEntity", async () => {
    showEntityCreateForm()
    expect(modalCalls).toHaveLength(1)
    expect(modalCalls[0].title).toBe("新建世界对象")
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("create-entity-name").value = "雾岭"
    // jsdom 不保证 selected 属性跨 optgroup 生效，显式设置模拟用户选择（浏览器行为正常）
    document.getElementById("create-entity-type").value = "character"
    document.getElementById("create-entity-summary").value = "山岭"
    const handler = modalCalls[0].buttons[0].handler
    await handler()
    expect(apiMock.world.createEntity).toHaveBeenCalledWith(
      { name: "雾岭", entity_type: "character", summary: "山岭" },
      "p-ops",
    )
  })

  it("名称为空 toast 警告且不提交", async () => {
    showEntityCreateForm()
    document.body.innerHTML = modalCalls[0].html
    await modalCalls[0].buttons[0].handler()
    expect(toastCalls).toContainEqual(["请输入名称", "warning"])
    expect(apiMock.world.createEntity).not.toHaveBeenCalled()
  })

  it("相似对象确认取消后可从原表单重试", async () => {
    apiMock.world.createEntity
      .mockRejectedValueOnce({ status: 409, detail: { requires_confirmation: true, similar_entities: [{ name: "雾岭" }] } })
      .mockResolvedValueOnce({})
    showEntityCreateForm()
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("create-entity-name").value = "雾岭新村"
    document.getElementById("create-entity-type").value = "location"
    const handler = modalCalls[0].buttons[0].handler

    expect(await handler()).toBe(false)
    expect(confirmCalls).toHaveLength(1)
    confirmCalls[0].onCancel()
    expect(modalCalls).toHaveLength(2)
    expect(modalCalls[1].html).toContain('value="雾岭新村"')
    document.body.innerHTML = modalCalls[1].html
    await modalCalls[1].buttons[0].handler()
    expect(apiMock.world.createEntity).toHaveBeenCalledTimes(2)
  })
})

describe("showKnowledgeForm", () => {
  const knowledge = (overrides = {}) => ({
    id: "knowledge-1",
    character_id: "e3",
    target_id: "e1",
    target_type: "location",
    target_name: "沉钟港",
    target_entity_type: "location",
    knowledge_level: "rumor",
    known_content: "听说港底有钟",
    misconception: null,
    source_chapter_index: 2,
    is_public_baseline: false,
    status: "canonical",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  })

  it("以作者语言展示当前、历史与同位置重复，不显示 raw enum 或 ID", async () => {
    apiMock.world.listKnowledge.mockResolvedValue({
      items: [
        knowledge(),
        knowledge({ id: "knowledge-2", knowledge_level: "false_belief", misconception: "相信钟会赐福", updated_at: "2026-01-01T00:00:00Z" }),
        knowledge({ id: "knowledge-3", source_chapter_index: 1, status: "archived" }),
      ],
      total: 3,
    })

    await showKnowledgeForm("e3")
    document.body.innerHTML = modalCalls[0].html
    const text = document.body.textContent

    expect(text).toContain("人物会怎样理解")
    expect(text).toContain("沉钟港")
    expect(text).toContain("地点")
    expect(text).toContain("听说过")
    expect(text).toContain("相信错误版本")
    expect(text).toContain("同一生效点有 2 条有效记录")
    expect(text).toContain("已归档")
    expect(text).not.toContain("false_belief")
    expect(text).not.toContain("knowledge-1")
  })

  it("从目标真实类型创建检查点，并在同一位置默认更新", async () => {
    await showKnowledgeForm("e3")
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("knowledge-target-id").value = "e1"
    document.getElementById("knowledge-level").value = "rumor"
    document.getElementById("knowledge-content").value = "码头传闻"
    document.getElementById("knowledge-chapter").value = "2"
    await modalCalls[0].buttons[0].handler()
    expect(apiMock.world.createKnowledge).toHaveBeenCalledWith("e3", expect.objectContaining({
      target_id: "e1",
      target_type: "location",
      source_chapter_index: 2,
    }), "p-ops")

    modalCalls = []
    apiMock.world.createKnowledge.mockClear()
    apiMock.world.listKnowledge.mockResolvedValue({
      items: [
        knowledge({ id: "knowledge-older", updated_at: "2025-01-01T00:00:00Z" }),
        knowledge({ id: "knowledge-newer", updated_at: "2026-01-01T00:00:00Z" }),
      ],
      total: 2,
    })
    await showKnowledgeForm("e3")
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("knowledge-target-id").value = "e1"
    document.getElementById("knowledge-level").value = "partial"
    document.getElementById("knowledge-content").value = "修正后的有限内容"
    document.getElementById("knowledge-chapter").value = "2"
    await modalCalls[0].buttons[0].handler()
    expect(apiMock.world.updateKnowledge).toHaveBeenCalledWith("knowledge-newer", expect.objectContaining({
      knowledge_level: "partial",
      source_chapter_index: 2,
    }), "p-ops")
    expect(apiMock.world.createKnowledge).not.toHaveBeenCalled()
  })

  it("连续点击保存只创建一个认知检查点", async () => {
    let finishCreate
    apiMock.world.createKnowledge.mockImplementation(() => new Promise((resolve) => {
      finishCreate = resolve
    }))
    await showKnowledgeForm("e3")
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("knowledge-target-id").value = "e1"
    document.getElementById("knowledge-level").value = "rumor"
    document.getElementById("knowledge-content").value = "码头传闻"
    document.getElementById("knowledge-chapter").value = "3"
    const handler = modalCalls[0].buttons[0].handler

    const firstSave = handler()
    const secondSave = handler()
    await Promise.resolve()

    expect(apiMock.world.createKnowledge).toHaveBeenCalledTimes(1)
    expect(await secondSave).toBe(false)
    finishCreate({})
    await firstSave
  })

  it("归档使用 PUT status，不调用硬删除", async () => {
    apiMock.world.listKnowledge.mockResolvedValue({ items: [knowledge()], total: 1 })
    setBridgeOverrides({
      showModalHtml: (title, html, buttons, options) => {
        captureModal(title, html, buttons, options)
        document.body.innerHTML = html
      },
    })
    await showKnowledgeForm("e3")
    document.querySelector("[data-knowledge-archive]").click()
    await vi.waitFor(() => expect(apiMock.world.updateKnowledge).toHaveBeenCalledWith(
      "knowledge-1",
      { status: "archived" },
      "p-ops",
    ))
    expect(apiMock.world.deleteKnowledge).toBeUndefined()
  })

  it("项目切换后忽略晚到的保存反馈和模态重开", async () => {
    const state = { currentProjectId: "p-ops", currentView: "world" }
    setBridgeOverrides({ state })
    apiMock.world.listKnowledge.mockResolvedValue({ items: [knowledge()], total: 1 })
    let finishUpdate
    apiMock.world.updateKnowledge.mockImplementation(() => new Promise((resolve) => { finishUpdate = resolve }))

    await showKnowledgeForm("e3")
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("knowledge-target-id").value = "e1"
    document.getElementById("knowledge-level").value = "partial"
    document.getElementById("knowledge-chapter").value = "2"
    const saving = modalCalls[0].buttons[0].handler()
    state.currentProjectId = "p-other"
    finishUpdate({})
    await saving

    expect(modalCalls).toHaveLength(1)
    expect(toastCalls).not.toContainEqual(["认知检查点已修正", "success"])
  })
})

describe("editEntity", () => {
  it("canonical 实体：updateEntity；candidate 实体：promoteEntity（编辑后采用）", async () => {
    editEntity("e1")
    expect(modalCalls[0].title).toBe("编辑世界对象")
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("edit-entity-name").value = "沉钟港·改"
    await modalCalls[0].buttons[0].handler()
    expect(apiMock.world.updateEntity).toHaveBeenCalledWith("e1", expect.objectContaining({ name: "沉钟港·改" }), "p-ops")

    modalCalls = []
    editEntity("e2")
    expect(modalCalls[0].title).toBe("编辑后采用世界对象")
    document.body.innerHTML = modalCalls[0].html
    await modalCalls[0].buttons[0].handler()
    expect(apiMock.world.promoteEntity).toHaveBeenCalledWith("e2", "p-ops", expect.objectContaining({ name: "月廷" }))
  })
})

describe("deleteEntity / promoteEntity", () => {
  it("deleteEntity 二次确认后调 deleteEntity API", async () => {
    deleteEntity("e1")
    expect(confirmCalls).toHaveLength(1)
    expect(confirmCalls[0].confirmText).toBe("确认删除")
    await confirmCalls[0].onConfirm()
    expect(apiMock.world.deleteEntity).toHaveBeenCalledWith("e1", "p-ops")
  })

  it("promoteEntity 二次确认后调 promoteEntity API", async () => {
    promoteEntity("e2")
    expect(confirmCalls[0].message).toContain("月廷")
    await confirmCalls[0].onConfirm()
    expect(apiMock.world.promoteEntity).toHaveBeenCalledWith("e2", "p-ops")
  })
})

describe("markEntityReviewed", () => {
  it("详情拉取失败也用列表数据标记 needs_review=false", async () => {
    const ok = await markEntityReviewed("e1")
    expect(ok).toBe(true)
    const [id, payload, projectId] = apiMock.world.updateEntity.mock.calls[0]
    expect(id).toBe("e1")
    expect(projectId).toBe("p-ops")
    expect(payload.content_json._meta.needs_review).toBe(false)
    expect(payload.content_json._meta.reviewed_from).toBe("world_objects")
  })

  it("离开原子视图后旧 mutation 完成不刷新或提示新视图", async () => {
    const state = { currentProjectId: "p-ops", currentView: "world", currentSubView: "objects" }
    const router = { refresh: vi.fn(async () => true) }
    const update = deferred()
    apiMock.world.getEntity.mockResolvedValueOnce(ENTITIES[0])
    apiMock.world.updateEntity.mockReturnValueOnce(update.promise)
    setBridgeOverrides({ state, router })

    const marking = markEntityReviewed("e1")
    await vi.waitFor(() => expect(apiMock.world.updateEntity).toHaveBeenCalled())
    state.currentSubView = "relations"
    update.resolve({})

    expect(await marking).toBe(true)
    expect(apiMock.world.updateEntity).toHaveBeenCalledWith("e1", expect.any(Object), "p-ops")
    expect(router.refresh).not.toHaveBeenCalled()
    expect(toastCalls).toHaveLength(0)
  })
})

describe("acceptCandidate / ignoreCandidate（乐观钩子）", () => {
  it("成功：乐观移除 + API + refresh", async () => {
    const remove = vi.fn(async () => ({ snapshot: true }))
    const restore = vi.fn(async () => {})
    registerCandidateListHooks({ removeOptimistically: remove, restoreSnapshot: restore })
    await acceptCandidate("c1")
    await confirmCalls[0].onConfirm()
    expect(remove).toHaveBeenCalledWith("c1")
    expect(apiMock.world.promoteEntity).toHaveBeenCalledWith("c1", "p-ops")
    expect(restore).not.toHaveBeenCalled()
  })

  it("失败：恢复快照 + toast", async () => {
    apiMock.world.promoteEntity = vi.fn(async () => { throw new Error("冲突") })
    const remove = vi.fn(async () => ({ snapshot: true }))
    const restore = vi.fn(async () => {})
    registerCandidateListHooks({ removeOptimistically: remove, restoreSnapshot: restore })
    await acceptCandidate("c1")
    await confirmCalls[0].onConfirm()
    expect(restore).toHaveBeenCalledWith({ snapshot: true })
    expect(toastCalls).toContainEqual(["处理失败：冲突", "error"])
  })
})

describe("showResolveAliasForm", () => {
  it("模态挂载 referencePicker 并提交 resolveEntityAsAlias", async () => {
    showResolveAliasForm("c1")
    expect(modalCalls).toHaveLength(1)
    expect(modalCalls[0].title).toBe("设为别名")
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("alias-target-id").value = "e1"
    document.getElementById("alias-edit-text").value = "潮声行会"
    // jsdom selected 属性跨 option 解析不可靠，显式设置（浏览器行为正常）
    document.getElementById("alias-edit-type").value = "alias"
    await modalCalls[0].buttons[0].handler()
    expect(apiMock.world.resolveEntityAsAlias).toHaveBeenCalledWith(
      "c1",
      { target_entity_id: "e1", alias: "潮声行会", alias_type: "alias" },
      "p-ops",
    )
  })

  it("候选不存在 toast 报错", () => {
    showResolveAliasForm("nope")
    expect(toastCalls).toContainEqual(["未找到目标待处理项", "error"])
    expect(modalCalls).toHaveLength(0)
  })

  it.each([
    ["设为别名", () => showResolveAliasForm("c1"), "alias-target-id", "resolveEntityAsAlias"],
    ["合并对象", () => showMergeForm("c1"), "merge-target-id", "mergeEntity"],
  ])("%s 缺少目标时保留弹窗且不调接口", async (_label, openForm, targetId, apiMethod) => {
    openForm()
    document.body.innerHTML = modalCalls[0].html
    document.getElementById(targetId).value = ""

    await expect(modalCalls[0].buttons[0].handler()).resolves.toBe(false)
    expect(apiMock.world[apiMethod]).not.toHaveBeenCalled()
    expect(confirmCalls).toHaveLength(0)
  })
})

describe("表单前置校验保留弹窗", () => {
  it("回滚索引无效时返回 false 且不调接口", async () => {
    showRollbackForm("e1")
    document.body.innerHTML = modalCalls[0].html
    Object.defineProperty(document.getElementById("rollback-scene-index"), "value", {
      configurable: true,
      value: "not-a-number",
    })

    await expect(modalCalls[0].buttons[0].handler()).resolves.toBe(false)
    expect(apiMock.world.rollbackEntity).not.toHaveBeenCalled()
  })

  it.each([
    ["未选目标", "", "unknown", ""],
    ["错误认知未填误解", "e2", "false_belief", ""],
  ])("知识边界：%s 时返回 false 且不调接口", async (_label, targetId, level, misconception) => {
    await showKnowledgeForm("e1")
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("knowledge-target-id").value = targetId
    document.getElementById("knowledge-level").value = level
    document.getElementById("knowledge-misconception").value = misconception

    await expect(modalCalls[0].buttons[0].handler()).resolves.toBe(false)
    expect(apiMock.world.createKnowledge).not.toHaveBeenCalled()
  })

  it("融合建议未选可应用项时返回 false 且不调接口", async () => {
    showEntityFusionSuggestions({ raw: { result: { suggestions: [{
      action: "merge",
      source_entity_id: "e1",
      source_entity_name: "沉钟港",
      target_entity_id: "e2",
      target_entity_name: "月廷",
    }] } } })
    document.body.innerHTML = modalCalls[0].html
    document.querySelector("[data-fusion-key]").checked = false

    await expect(modalCalls[0].buttons[0].handler()).resolves.toBe(false)
    expect(apiMock.world.applyEntityFusionSuggestions).not.toHaveBeenCalled()
  })

  it("批量解析未选主对象时返回 false 且不调接口", async () => {
    const entities = [
      { id: "bulk-1", name: "旧港", entity_type: "location", status: "canonical" },
      { id: "bulk-2", name: "新港", entity_type: "location", status: "canonical" },
    ]
    syncWorldListRegistry({ entities })
    entities.forEach((item) => toggleBulkSelection("world-objects", item.id, true))
    runObjectsBulkAction("fuse-entities", entities)
    document.body.innerHTML = modalCalls[0].html
    document.querySelector('input[name="world-bulk-target"]:checked').checked = false

    await expect(modalCalls[0].buttons[0].handler()).resolves.toBe(false)
    expect(apiMock.world.applyEntityFusionSuggestions).not.toHaveBeenCalled()
    expect(confirmCalls).toHaveLength(0)
  })
})

describe("当前表单请求失败保留弹窗", () => {
  it.each([
    ["设为别名", "resolveEntityAsAlias", () => {
      showResolveAliasForm("c1")
      document.body.innerHTML = modalCalls[0].html
      document.getElementById("alias-target-id").value = "e1"
    }],
    ["回滚对象", "rollbackEntity", () => {
      showRollbackForm("e1")
      document.body.innerHTML = modalCalls[0].html
    }],
    ["添加知识边界", "createKnowledge", async () => {
      await showKnowledgeForm("e1")
      document.body.innerHTML = modalCalls[0].html
      document.getElementById("knowledge-target-id").value = "e3"
    }],
    ["应用融合建议", "applyEntityFusionSuggestions", () => {
      showEntityFusionSuggestions({ raw: { result: { suggestions: [{
        action: "merge",
        source_entity_id: "e1",
        source_entity_name: "沉钟港",
        target_entity_id: "e2",
        target_entity_name: "月廷",
      }] } } })
      document.body.innerHTML = modalCalls[0].html
    }],
  ])("%s API 失败时返回 false 供原位重试", async (_label, apiMethod, openValidForm) => {
    apiMock.world[apiMethod].mockRejectedValueOnce(new Error("请求失败"))
    await openValidForm()

    await expect(modalCalls[0].buttons[0].handler()).resolves.toBe(false)
    expect(apiMock.world[apiMethod]).toHaveBeenCalledTimes(1)
    expect(toastCalls).toContainEqual(["请求失败", "error"])
  })

  it("合并确认请求失败时返回 false 供原位重试", async () => {
    apiMock.world.mergeEntity.mockRejectedValueOnce(new Error("合并失败"))
    showMergeForm("c1")
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("merge-target-id").value = "e1"

    await expect(modalCalls[0].buttons[0].handler()).resolves.toBe(false)
    await expect(confirmCalls[0].onConfirm()).resolves.toBe(false)
    expect(apiMock.world.mergeEntity).toHaveBeenCalledWith("c1", "e1", "p-ops")
    expect(toastCalls).toContainEqual(["合并失败", "error"])
  })

  it("批量融合确认请求失败时返回 false 供原位重试", async () => {
    const entities = [
      { id: "bulk-1", name: "旧港", entity_type: "location", status: "canonical" },
      { id: "bulk-2", name: "新港", entity_type: "location", status: "canonical" },
    ]
    apiMock.world.applyEntityFusionSuggestions.mockRejectedValueOnce(new Error("融合失败"))
    syncWorldListRegistry({ entities })
    entities.forEach((item) => toggleBulkSelection("world-objects", item.id, true))
    runObjectsBulkAction("fuse-entities", entities)
    document.body.innerHTML = modalCalls[0].html

    await expect(modalCalls[0].buttons[0].handler()).resolves.toBe(false)
    await expect(confirmCalls[0].onConfirm()).resolves.toBe(false)
    expect(apiMock.world.applyEntityFusionSuggestions).toHaveBeenCalledTimes(1)
    expect(toastCalls).toContainEqual(["融合失败", "error"])
  })
})
