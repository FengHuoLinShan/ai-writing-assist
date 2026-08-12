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
  showEntityCreateForm,
  showResolveAliasForm,
  syncWorldListRegistry,
} from "../../../vue/views/world/logic/worldEntityOps.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const ENTITIES = [
  { id: "e1", name: "沉钟港", entity_type: "location", status: "canonical", summary: "旧港" },
  { id: "e2", name: "月廷", entity_type: "organization", status: "candidate", summary: "教团" },
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
  syncWorldListRegistry({ entities: ENTITIES, candidates: CANDIDATES, entityTypes: [{ value: "location", label: "地点" }, { value: "organization", label: "组织" }] })
  registerCandidateListHooks({})
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
})
