import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import {
  assignInformationPlan,
  deleteThread,
  executeBulkOutlineAction,
  runBulkOutlineAction,
  showCreateThreadForm,
  updateForeshadowingStatus,
} from "../../../vue/views/outline/logic/outlineStructureOps.js"
import {
  clearAllBulkSelections,
  getBulkSelection,
} from "../../../vue/views/outline/logic/outlineBulkSelection.js"

function deferred() {
  let resolve
  let reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

function installConfirmHost(onConfirm) {
  document.body.innerHTML = '<div id="modal-body"></div>'
  setBridgeOverrides({
    confirmAction: (message, handler) => {
      const owner = document.createElement("p")
      owner.textContent = message
      document.getElementById("modal-body").replaceChildren(owner)
      onConfirm(handler)
    },
  })
}

describe("outline structure mutation lifecycle", () => {
  let state
  let api
  let router
  let toast
  let modal

  beforeEach(() => {
    state = { currentProjectId: "p1", currentView: "outline", currentSubView: "threads" }
    api = { outline: {} }
    router = { refresh: vi.fn(async () => true) }
    toast = vi.fn()
    modal = null
    clearAllBulkSelections()
    setBridgeOverrides({
      api,
      state,
      router,
      toast,
      showModalHtml: (title, html, buttons) => { modal = { title, html, buttons } },
    })
  })

  afterEach(() => {
    resetBridgeOverrides()
    clearAllBulkSelections()
  })

  it("离开信息推进发起页后不刷新或提示新子页", async () => {
    const request = deferred()
    api.outline.updateForeshadowing = vi.fn(() => request.promise)

    const pending = assignInformationPlan(
      "f1",
      "foreshadowing",
      "t1",
      [{ id: "f1", related_thread_ids: [] }],
      [],
    )
    state.currentSubView = "arcs"
    request.resolve()

    await expect(pending).resolves.toBe(true)
    expect(api.outline.updateForeshadowing).toHaveBeenCalledWith("f1", "p1", { related_thread_ids: ["t1"] })
    expect(router.refresh).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it("模态写入成功后离开子视图时返回成功且不刷新新页", async () => {
    const request = deferred()
    api.outline.createThread = vi.fn(() => request.promise)
    showCreateThreadForm()
    document.body.innerHTML = modal.html
    document.getElementById("create-thread-name").value = "主线"

    const pending = modal.buttons[0].handler()
    state.currentSubView = "arcs"
    request.resolve({})

    await expect(pending).resolves.toBe(true)
    expect(api.outline.createThread).toHaveBeenCalledWith("p1", {
      name: "主线",
      thread_type: "main",
      summary: "",
    })
    expect(router.refresh).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it("模态写入失败后已离开子视图时也收口旧模态", async () => {
    const request = deferred()
    api.outline.createThread = vi.fn(() => request.promise)
    showCreateThreadForm()
    document.body.innerHTML = modal.html
    document.getElementById("create-thread-name").value = "主线"

    const pending = modal.buttons[0].handler()
    state.currentSubView = "arcs"
    request.reject(new Error("创建失败"))

    await expect(pending).resolves.toBe(true)
    expect(router.refresh).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it("当前子视图内失败时保留模态供重试", async () => {
    api.outline.createThread = vi.fn(async () => { throw new Error("创建失败") })
    showCreateThreadForm()
    document.body.innerHTML = modal.html
    document.getElementById("create-thread-name").value = "主线"

    await expect(modal.buttons[0].handler()).resolves.toBe(false)
    expect(router.refresh).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("创建失败", "error")
  })

  it("表单校验失败时明确保留当前模态", async () => {
    api.outline.createThread = vi.fn()
    showCreateThreadForm()
    document.body.innerHTML = modal.html

    await expect(modal.buttons[0].handler()).resolves.toBe(false)
    expect(api.outline.createThread).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("请输入名称", "warning")
  })

  it.each(["resolve", "reject"])("同页新模态替换后旧表单写入 %s 均不刷新或提示", async (outcome) => {
    const request = deferred()
    api.outline.createThread = vi.fn(() => request.promise)
    showCreateThreadForm()
    document.body.innerHTML = modal.html
    document.getElementById("create-thread-name").value = "主线"

    const pending = modal.buttons[0].handler()
    await vi.waitFor(() => expect(api.outline.createThread).toHaveBeenCalledOnce())
    const replacement = document.createElement("input")
    replacement.id = "create-thread-name"
    document.body.replaceChildren(replacement)
    if (outcome === "resolve") request.resolve({})
    else request.reject(new Error("旧模态失败"))

    await expect(pending).resolves.toBe(true)
    expect(router.refresh).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it.each(["resolve", "reject"])("同页新确认框替换后旧删除 %s 均收口且无副作用", async (outcome) => {
    const request = deferred()
    let confirm
    api.outline.deleteThread = vi.fn(() => request.promise)
    installConfirmHost((handler) => { confirm = handler })
    deleteThread("t1")

    const pending = confirm()
    await vi.waitFor(() => expect(api.outline.deleteThread).toHaveBeenCalledWith("t1", "p1"))
    document.getElementById("modal-body").replaceChildren(document.createElement("p"))
    if (outcome === "resolve") request.resolve({})
    else request.reject(new Error("旧确认框失败"))

    await expect(pending).resolves.toBe(true)
    expect(router.refresh).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it("当前确认框内 API 失败时保留确认框供重试", async () => {
    let confirm
    api.outline.deleteThread = vi.fn(async () => { throw new Error("删除失败") })
    installConfirmHost((handler) => { confirm = handler })
    deleteThread("t1")

    await expect(confirm()).resolves.toBe(false)
    expect(router.refresh).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("删除失败", "error")
  })

  it("仍在发起页时保留原有写入和刷新语义", async () => {
    api.outline.updateForeshadowing = vi.fn(async () => ({}))

    await expect(updateForeshadowingStatus("f1", "planted")).resolves.toBe(true)

    expect(api.outline.updateForeshadowing).toHaveBeenCalledWith("f1", "p1", { status: "planted" })
    expect(router.refresh).toHaveBeenCalledOnce()
    expect(toast).toHaveBeenCalledWith("伏笔状态已更新", "success")
  })

  it("批量写入完成前切换子页时不清空旧选择或刷新新页", async () => {
    const request = deferred()
    api.outline.deleteThread = vi.fn(() => request.promise)
    getBulkSelection("outline-threads").add("t1")

    const pending = executeBulkOutlineAction(
      "outline-threads",
      "delete-threads",
      [{ id: "t1", name: "主线" }],
    )
    state.currentSubView = "arcs"
    request.resolve()

    await expect(pending).resolves.toBe(false)
    expect(api.outline.deleteThread).toHaveBeenCalledWith("t1", "p1")
    expect(getBulkSelection("outline-threads").has("t1")).toBe(true)
    expect(router.refresh).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it("批量确认框被同页新模态替换时保留选择", async () => {
    const request = deferred()
    let confirm
    api.outline.deleteThread = vi.fn(() => request.promise)
    getBulkSelection("outline-threads").add("t1")
    installConfirmHost((handler) => { confirm = handler })
    runBulkOutlineAction("outline-threads", "delete-threads", [{ id: "t1", name: "主线" }])

    const pending = confirm()
    await vi.waitFor(() => expect(api.outline.deleteThread).toHaveBeenCalledWith("t1", "p1"))
    document.getElementById("modal-body").replaceChildren(document.createElement("p"))
    request.resolve({})

    await expect(pending).resolves.toBe(true)
    expect(getBulkSelection("outline-threads").has("t1")).toBe(true)
    expect(router.refresh).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })
})
