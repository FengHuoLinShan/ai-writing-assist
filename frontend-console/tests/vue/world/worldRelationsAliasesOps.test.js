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
  showRelationReviewEditForm,
  syncRelationsAliasesRegistry,
} from "../../../vue/views/world/logic/worldRelationsAliasesOps.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const RELATIONS = [
  { id: "r1", source_name: "林澈", source_id: "e1", target_name: "沉钟港", target_id: "e2", relation_kind: "social", relation_type: "friend_of", description: "驻守旧港", status: "canonical", strength: 0.7 },
]
const ALIASES = [
  { entity_id: "e1", alias: "小名", alias_kind: "name", alias_type: "nickname", entity_name: "主角", status: "canonical", source: "manual", confidence: 1.0 },
]

let modalCalls
let confirmCalls
let toastCalls
let apiMock
let routerMock

function captureModal(title, html, buttons, options) {
  modalCalls.push({ title, html, buttons, options })
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

function installModalHost(html) {
  document.body.innerHTML = '<div id="modal-overlay"><div id="modal-body"></div></div>'
  const body = document.getElementById("modal-body")
  body.innerHTML = html
  return body
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
  routerMock = { navigate: vi.fn(), refresh: vi.fn(async () => true) }
  setBridgeOverrides({
    api: apiMock,
    state: { currentProjectId: "p-ra", currentView: "world" },
    toast: (...args) => toastCalls.push(args),
    showModalHtml: captureModal,
    confirmAction: (message, onConfirm, confirmText) => {
      confirmCalls.push({ message, onConfirm, confirmText })
    },
    confirm: vi.fn(() => true),
    router: routerMock,
  })
  syncRelationsAliasesRegistry({ relations: RELATIONS, aliases: ALIASES })
})

afterEach(() => {
  resetBridgeOverrides()
})

it.each([
  ["关系", showRelationCreateForm, 2],
  ["别名", showAliasCreateForm, 1],
])("%s实体预取期间切换项目时不打开旧项目模态", async (_label, showCreateForm, expectedRequests) => {
  const state = { currentProjectId: "p-ra", currentView: "world" }
  let resolveEntities
  const pendingEntities = new Promise((resolve) => { resolveEntities = resolve })
  setBridgeOverrides({ state })
  apiMock.world.listEntities.mockReturnValue(pendingEntities)

  const opening = showCreateForm()
  expect(apiMock.world.listEntities).toHaveBeenCalledTimes(expectedRequests)
  expect(apiMock.world.listEntities).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p-ra" }))

  state.currentProjectId = "p-other"
  resolveEntities({ items: [], total: 0 })
  await opening

  expect(modalCalls).toHaveLength(0)
})

it.each([
  ["关系", showRelationCreateForm],
  ["别名", showAliasCreateForm],
])("%s实体预取期间离开当前子视图时不打开过期模态", async (_label, showCreateForm) => {
  const state = { currentProjectId: "p-ra", currentView: "world", currentSubView: "relations" }
  let resolveEntities
  const pendingEntities = new Promise((resolve) => { resolveEntities = resolve })
  setBridgeOverrides({ state })
  apiMock.world.listEntities.mockReturnValue(pendingEntities)

  const opening = showCreateForm()
  state.currentSubView = "bible"
  resolveEntities({ items: [], total: 0 })
  await opening

  expect(modalCalls).toHaveLength(0)
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
      { source_id: "e1", source_type: "entity", target_id: "e2", target_type: "entity", relation_kind: expect.any(String), relation_type: "ally_of", description: "测试描述" },
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

  it("写入成功后离开子视图时返回成功且不刷新新页", async () => {
    const state = { currentProjectId: "p-ra", currentView: "world", currentSubView: "relations" }
    const request = deferred()
    apiMock.world.createRelationship.mockReturnValue(request.promise)
    setBridgeOverrides({ state })
    await showRelationCreateForm()
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("rel-source").value = "e1"
    document.getElementById("rel-target").value = "e2"

    const pending = modalCalls[0].buttons[0].handler()
    state.currentSubView = "aliases"
    request.resolve({})

    await expect(pending).resolves.toBe(true)
    expect(routerMock.refresh).not.toHaveBeenCalled()
    expect(toastCalls).toHaveLength(0)
  })

  it("写入失败后已离开子视图时也收口旧模态", async () => {
    const state = { currentProjectId: "p-ra", currentView: "world", currentSubView: "relations" }
    const request = deferred()
    apiMock.world.createRelationship.mockReturnValue(request.promise)
    setBridgeOverrides({ state })
    await showRelationCreateForm()
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("rel-source").value = "e1"
    document.getElementById("rel-target").value = "e2"

    const pending = modalCalls[0].buttons[0].handler()
    state.currentSubView = "aliases"
    request.reject(new Error("创建失败"))

    await expect(pending).resolves.toBe(true)
    expect(routerMock.refresh).not.toHaveBeenCalled()
    expect(toastCalls).toHaveLength(0)
  })

  it.each([
    ["成功", false],
    ["失败", true],
  ])("写入%s晚到时不污染同路由新模态", async (_label, rejects) => {
    const request = deferred()
    apiMock.world.createRelationship.mockReturnValue(request.promise)
    await showRelationCreateForm()
    const body = installModalHost(modalCalls[0].html)
    document.getElementById("rel-source").value = "e1"
    document.getElementById("rel-target").value = "e2"

    const pending = modalCalls[0].buttons[0].handler()
    await vi.waitFor(() => expect(apiMock.world.createRelationship).toHaveBeenCalled())
    body.innerHTML = "<p>新模态</p>"
    if (rejects) request.reject(new Error("旧请求失败"))
    else request.resolve({})

    await expect(pending).resolves.toBe(true)
    expect(body.textContent).toBe("新模态")
    expect(routerMock.refresh).not.toHaveBeenCalled()
    expect(toastCalls).toHaveLength(0)
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
      { entity_id: "e1", alias: "小名", alias_kind: "name", alias_type: "nickname" },
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

  it("写入成功后离开子视图时返回成功且不刷新新页", async () => {
    const state = { currentProjectId: "p-ra", currentView: "world", currentSubView: "aliases" }
    const request = deferred()
    apiMock.world.createAlias.mockReturnValue(request.promise)
    setBridgeOverrides({ state })
    await showAliasCreateForm()
    document.body.innerHTML = modalCalls[0].html
    document.getElementById("alias-entity").value = "e1"
    document.getElementById("alias-text").value = "小名"

    const pending = modalCalls[0].buttons[0].handler()
    state.currentSubView = "relations"
    request.resolve({})

    await expect(pending).resolves.toBe(true)
    expect(routerMock.refresh).not.toHaveBeenCalled()
    expect(toastCalls).toHaveLength(0)
  })
})

describe("showRelationReviewEditForm", () => {
  it("写入成功后离开子视图时返回成功且不关闭或刷新新页", async () => {
    const state = { currentProjectId: "p-ra", currentView: "world", currentSubView: "relations" }
    const request = deferred()
    const closeModal = vi.fn()
    apiMock.world.reviewEditRelationship.mockReturnValue(request.promise)
    setBridgeOverrides({ state, closeModal })
    showRelationReviewEditForm("r1")
    document.body.innerHTML = modalCalls[0].html

    const pending = modalCalls[0].buttons[0].handler()
    state.currentSubView = "aliases"
    request.resolve({})

    await expect(pending).resolves.toBe(true)
    expect(closeModal).not.toHaveBeenCalled()
    expect(routerMock.refresh).not.toHaveBeenCalled()
    expect(toastCalls).toHaveLength(0)
  })

  it("当前子视图内失败时保留模态供重试", async () => {
    apiMock.world.reviewEditRelationship.mockRejectedValue(new Error("采用失败"))
    showRelationReviewEditForm("r1")
    document.body.innerHTML = modalCalls[0].html

    await expect(modalCalls[0].buttons[0].handler()).resolves.toBe(false)
    expect(routerMock.refresh).not.toHaveBeenCalled()
    expect(toastCalls).toContainEqual(["采用失败", "error"])
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

  it("删除响应晚到时不提示或刷新同路由新模态", async () => {
    const request = deferred()
    apiMock.world.deleteRelationship.mockReturnValue(request.promise)
    deleteRelation("r1")
    const body = installModalHost("<p>确认删除</p>")

    const pending = confirmCalls[0].onConfirm()
    await vi.waitFor(() => expect(apiMock.world.deleteRelationship).toHaveBeenCalled())
    body.innerHTML = "<p>新模态</p>"
    request.resolve({})

    await expect(pending).resolves.toBe(true)
    expect(body.textContent).toBe("新模态")
    expect(routerMock.refresh).not.toHaveBeenCalled()
    expect(toastCalls).toHaveLength(0)
  })

  it("当前确认模态的 API 失败保留弹窗供重试", async () => {
    apiMock.world.deleteRelationship.mockRejectedValue(new Error("删除失败"))
    deleteRelation("r1")
    installModalHost("<p>确认删除</p>")

    await expect(confirmCalls[0].onConfirm()).resolves.toBe(false)
    expect(routerMock.refresh).not.toHaveBeenCalled()
    expect(toastCalls).toContainEqual(["删除失败", "error"])
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
    expect(routerMock.refresh).toHaveBeenCalledOnce()
    expect(toastCalls).toContainEqual(["关系已采用", "success"])
  })

  it("同项目切换子视图后延迟结果不刷新新页", async () => {
    const state = { currentProjectId: "p-ra", currentView: "world", currentSubView: "relations" }
    let resolveReview
    apiMock.world.reviewEditRelationship.mockReturnValue(new Promise((resolve) => { resolveReview = resolve }))
    setBridgeOverrides({ state })

    const pending = markRelationReviewed("r1")
    expect(apiMock.world.reviewEditRelationship).toHaveBeenCalledWith(
      "r1",
      { confirm_review: true },
      "p-ra",
    )
    state.currentSubView = "aliases"
    resolveReview({})

    expect(await pending).toBe(true)
    expect(routerMock.refresh).not.toHaveBeenCalled()
    expect(toastCalls).not.toContainEqual(["关系已采用", "success"])
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
