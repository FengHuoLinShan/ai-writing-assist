/**
 * worldRelationsAliasesOps 测试 — 模态表单与 API 交互（bridge 截获 showModalHtml/confirmAction）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"

import {
  showRelationCreateForm,
  showAliasCreateForm,
  deleteRelation,
  deleteAlias,
  markRelationReviewed,
  markAliasReviewed,
  syncRelationsAliasesRegistry,
} from "../../../vue/views/world/logic/worldRelationsAliasesOps.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const RELATIONS = [
  { id: "r1", source_name: "林澈", source_id: "e1", target_name: "沉钟港", target_id: "e2", relation_type: "friend_of", description: "驻守旧港", status: "canonical", strength: 0.7 },
]
const ALIASES = [
  { entity_id: "e1", alias: "小名", alias_type: "nickname", entity_name: "主角", status: "canonical", source: "manual", confidence: 1.0 },
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
  apiMock = {
    world: {
      createRelationship: vi.fn(async () => ({})),
      createAlias: vi.fn(async () => ({})),
      deleteRelationship: vi.fn(async () => ({})),
      deleteAlias: vi.fn(async () => ({})),
      reviewEditRelationship: vi.fn(async () => ({})),
      updateAlias: vi.fn(async () => ({})),
      listEntities: vi.fn(async () => ({
        items: [
          { id: "e1", name: "林澈", entity_type: "character", status: "canonical" },
          { id: "e2", name: "沉钟港", entity_type: "location", status: "canonical" },
        ],
        total: 2,
      })),
    },
  }
  setBridgeOverrides({
    api: apiMock,
    state: { currentProjectId: "p-ra", currentView: "world" },
    toast: (...args) => toastCalls.push(args),
    showModalHtml: captureModal,
    confirmAction: (message, onConfirm, confirmText) => {
      confirmCalls.push({ message, onConfirm, confirmText })
    },
    confirm: vi.fn(() => true),
    router: { navigate: vi.fn(), refresh: vi.fn(async () => true) },
  })
  syncRelationsAliasesRegistry({ relations: RELATIONS, aliases: ALIASES })
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("showRelationCreateForm", () => {
  it("打开新建模态并提交 createRelationship（实体选项同步嵌入 HTML）", async () => {
    await showRelationCreateForm()
    expect(modalCalls).toHaveLength(1)
    expect(modalCalls[0].title).toBe("新建关系")
    // 实体选项应已完整嵌入 HTML（async 函数先 fetch 再 showModalHtml）
    expect(modalCalls[0].html).toContain('id="rel-source"')
    expect(modalCalls[0].html).toContain('value="e1"')
    expect(modalCalls[0].html).toContain('value="e2"')
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("rel-source").value = "e1"
    document.getElementById("rel-target").value = "e2"
    document.getElementById("rel-type").value = "ally_of"
    document.getElementById("rel-desc").value = "测试描述"
    const handler = modalCalls[0].buttons[0].handler
    await handler()
    expect(apiMock.world.createRelationship).toHaveBeenCalledWith(
      { source_id: "e1", source_type: "entity", target_id: "e2", target_type: "entity", relation_type: "ally_of", description: "测试描述" },
      "p-ra",
    )
  })

  it("源/目标未选择时 toast 警告", async () => {
    await showRelationCreateForm()
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("rel-source").value = ""
    document.getElementById("rel-target").value = ""
    await modalCalls[0].buttons[0].handler()
    expect(toastCalls).toContainEqual(["请选择源对象和目标对象", "warning"])
    expect(apiMock.world.createRelationship).not.toHaveBeenCalled()
  })
})

describe("showAliasCreateForm", () => {
  it("打开新建模态并提交 createAlias（实体选项同步嵌入 HTML）", async () => {
    await showAliasCreateForm()
    expect(modalCalls).toHaveLength(1)
    expect(modalCalls[0].title).toBe("新建别名")
    // 实体选项已嵌入
    expect(modalCalls[0].html).toContain('id="alias-entity"')
    expect(modalCalls[0].html).toContain('value="e1"')
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("alias-entity").value = "e1"
    document.getElementById("alias-text").value = "小名"
    document.getElementById("alias-type").value = "nickname"
    const handler = modalCalls[0].buttons[0].handler
    await handler()
    expect(apiMock.world.createAlias).toHaveBeenCalledWith(
      { entity_id: "e1", alias: "小名", alias_type: "nickname" },
      "p-ra",
    )
  })

  it("空文本 toast 警告", async () => {
    await showAliasCreateForm()
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("alias-entity").value = "e1"
    document.getElementById("alias-text").value = ""
    await modalCalls[0].buttons[0].handler()
    expect(toastCalls).toContainEqual(["请选择对象并输入别名", "warning"])
    expect(apiMock.world.createAlias).not.toHaveBeenCalled()
  })
})

describe("deleteRelation", () => {
  it("确认后调 deleteRelationship", async () => {
    deleteRelation("r1")
    expect(confirmCalls).toHaveLength(1)
    expect(confirmCalls[0].confirmText).toBe("确认删除")
    await confirmCalls[0].onConfirm()
    expect(apiMock.world.deleteRelationship).toHaveBeenCalledWith("r1", { novel_id: "p-ra" })
  })
})

describe("deleteAlias", () => {
  it("确认后调 deleteAlias API", async () => {
    deleteAlias("e1", "小名")
    expect(confirmCalls).toHaveLength(1)
    expect(confirmCalls[0].confirmText).toBe('确认删除别名 "小名"')
    await confirmCalls[0].onConfirm()
    expect(apiMock.world.deleteAlias).toHaveBeenCalledWith("e1", "小名", { novel_id: "p-ra" })
  })

  it("缺少参数直接报错", () => {
    deleteAlias("", "")
    expect(toastCalls).toContainEqual(["参数错误：缺少实体 ID 或别名", "error"])
    expect(confirmCalls).toHaveLength(0)
  })
})

describe("markRelationReviewed", () => {
  it("调 reviewEditRelationship 并 refresh", async () => {
    const ok = await markRelationReviewed("r1")
    expect(ok).toBe(true)
    expect(apiMock.world.reviewEditRelationship).toHaveBeenCalledWith(
      "r1",
      { confirm_review: true },
      "p-ra",
    )
  })
})

describe("markAliasReviewed", () => {
  it("调 updateAlias 并 refresh", async () => {
    const ok = await markAliasReviewed("e1", "小名")
    expect(ok).toBe(true)
    expect(apiMock.world.updateAlias).toHaveBeenCalledWith(
      "e1", "小名",
      expect.objectContaining({ status: "canonical", needs_review: false, reviewed_by: "manual", reviewed_from: "world_aliases" }),
      { novel_id: "p-ra" },
    )
  })

  it("缺少参数返回 false", async () => {
    const ok = await markAliasReviewed("", "")
    expect(ok).toBe(false)
  })
})
