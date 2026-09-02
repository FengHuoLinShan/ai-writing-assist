/**
 * 回收站与项目 modal 流程测试 — 对应原 tests/projectView.test.js 的 modal 用例。
 * 全局 modal 用注入替身捕获内容，随后直接在 document 中驱动按钮。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { showRecycleBin } from "../../../vue/views/project/logic/recycleBin.js"
import { projectSession } from "../../../vue/views/project/projectSession.js"
import {
  deleteProject,
  editProject,
  importAsNewProject,
  showCreateForm,
} from "../../../vue/views/project/logic/projectModals.js"

function deletedItem(id, overrides = {}) {
  return {
    id,
    title: `已删项目${id}`,
    deleted_at: "2026-07-10T00:00:00Z",
    ...overrides,
  }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

/** 捕获 showModalHtml 调用并把内容写入 document（模拟外壳 modal 已打开）。 */
function stubModal() {
  const showModalHtml = vi.fn((title, html) => {
    document.body.innerHTML = `<div id="modal-body">${html}</div>`
  })
  setBridgeOverrides({ showModalHtml })
  return showModalHtml
}

beforeEach(() => {
  vi.clearAllMocks()
  document.body.innerHTML = ""
  projectSession.recycleBinSkip = 0
  globalThis.api.projects.listDeleted = vi.fn(async () => ({
    items: [deletedItem("d1"), deletedItem("d2")],
    total: 2,
  }))
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("回收站", () => {
  it("渲染列表、分页与操作按钮", async () => {
    const showModalHtml = stubModal()
    await showRecycleBin(0)
    expect(showModalHtml).toHaveBeenCalledWith("回收站", expect.stringContaining("recycle-bin__list"), [], { size: "large" })
    expect(document.querySelectorAll(".recycle-bin__item")).toHaveLength(2)
    expect(document.querySelector('.restore-project-btn[data-id="d1"]')).not.toBeNull()
    expect(document.querySelector('.perm-delete-project-btn[data-id="d2"]')).not.toBeNull()
    expect(document.getElementById("recycle-bulk-restore").disabled).toBe(true)
    expect(document.getElementById("recycle-bulk-delete").disabled).toBe(true)
    expect(document.getElementById("recycle-prev-page").disabled).toBe(true)
    expect(document.getElementById("recycle-next-page").disabled).toBe(true)
  })

  it("选择变化时同步批量操作可用状态", async () => {
    stubModal()
    await showRecycleBin(0)
    const checkbox = document.querySelector('.recycle-project-checkbox[data-id="d1"]')
    const bulkRestore = document.getElementById("recycle-bulk-restore")
    const bulkDelete = document.getElementById("recycle-bulk-delete")

    checkbox.checked = true
    checkbox.dispatchEvent(new Event("change"))
    expect(bulkRestore.disabled).toBe(false)
    expect(bulkDelete.disabled).toBe(false)

    checkbox.checked = false
    checkbox.dispatchEvent(new Event("change"))
    expect(bulkRestore.disabled).toBe(true)
    expect(bulkDelete.disabled).toBe(true)
  })

  it.each([
    ["下一页", 0, 20, "recycle-next-page"],
    ["上一页", 40, 20, "recycle-prev-page"],
  ])("%s重绘后恢复同方向分页按钮焦点且不滚动", async (_label, initialSkip, expectedSkip, buttonId) => {
    globalThis.api.projects.listDeleted = vi.fn(async (skip) => ({
      items: [deletedItem(`page-${skip}`)],
      total: 80,
    }))
    stubModal()
    await showRecycleBin(initialSkip)
    const originalButton = document.getElementById(buttonId)
    originalButton.focus()
    const focusSpy = vi.spyOn(HTMLElement.prototype, "focus")

    try {
      await originalButton.onclick()
      const replacementButton = document.getElementById(buttonId)

      expect(replacementButton).not.toBe(originalButton)
      expect(document.activeElement).toBe(replacementButton)
      expect(focusSpy).toHaveBeenCalledWith({ preventScroll: true })
      expect(globalThis.api.projects.listDeleted).toHaveBeenLastCalledWith(expectedSkip, 20)
    } finally {
      focusSpy.mockRestore()
    }
  })

  it("零选择时批量 handler 仍保留防御提示", async () => {
    stubModal()
    const confirmAction = vi.fn()
    setBridgeOverrides({ confirmAction })
    await showRecycleBin(0)

    await document.getElementById("recycle-bulk-restore").onclick()
    document.getElementById("recycle-bulk-delete").onclick()

    expect(globalThis.toast).toHaveBeenCalledTimes(2)
    expect(globalThis.toast).toHaveBeenLastCalledWith("请先选择作品", "warning")
    expect(globalThis.api.projects.restore).not.toHaveBeenCalled()
    expect(globalThis.api.projects.permanentDeleteMany).not.toHaveBeenCalled()
    expect(confirmAction).not.toHaveBeenCalled()
  })

  it("恢复项目后局部更新背景列表并重载回收站", async () => {
    stubModal()
    setBridgeOverrides({ state: globalThis.state })
    globalThis.state.currentProjectId = null
    globalThis.state.currentProject = null
    globalThis.state.projects = []
    globalThis.api.projects.restore = vi.fn(async () => ({}))
    globalThis.api.projects.list = vi.fn(async () => ({ items: [{ id: "d1", title: "已恢复项目" }] }))
    await showRecycleBin(0)
    await document.querySelector('.restore-project-btn[data-id="d1"]').onclick()

    expect(globalThis.api.projects.restore).toHaveBeenCalledWith("d1")
    expect(globalThis.toast).toHaveBeenCalledWith("作品已恢复", "success")
    expect(globalThis.api.projects.list).toHaveBeenCalledTimes(1)
    expect(globalThis.state.projects).toEqual([{ id: "d1", title: "已恢复项目" }])
    expect(globalThis.router.refresh).not.toHaveBeenCalled()
    expect(globalThis.api.projects.listDeleted).toHaveBeenCalledTimes(2)
  })

  it.each([
    ["单个", "single"],
    ["批量", "bulk"],
  ])("%s恢复的背景局部更新期间弹窗换主时不重开回收站", async (_label, kind) => {
    document.body.innerHTML = `
      <main id="workspace-content"><section class="project-catalog"></section></main>
      <div id="modal-overlay" class="hidden"><div id="modal-body"></div></div>
    `
    globalThis.state.currentView = "project"
    globalThis.state.currentProjectId = null
    globalThis.state.currentProject = null
    globalThis.state.projects = []
    setBridgeOverrides({
      state: globalThis.state,
      showModalHtml: vi.fn((_title, html) => {
        document.getElementById("modal-body").innerHTML = html
        document.getElementById("modal-overlay").classList.remove("hidden")
      }),
    })
    globalThis.api.projects.restore = vi.fn(async () => ({}))
    const reload = deferred()
    globalThis.api.projects.list = vi.fn(() => reload.promise)
    await showRecycleBin(0)

    let pending
    if (kind === "bulk") {
      const checkbox = document.querySelector('.recycle-project-checkbox[data-id="d1"]')
      checkbox.checked = true
      checkbox.dispatchEvent(new Event("change"))
      pending = document.getElementById("recycle-bulk-restore").onclick()
    } else {
      pending = document.querySelector('.restore-project-btn[data-id="d1"]').onclick()
    }
    await vi.waitFor(() => expect(globalThis.api.projects.list).toHaveBeenCalled())
    document.getElementById("modal-body").innerHTML = '<div class="create-project-form"></div>'
    reload.resolve({ items: [{ id: "restored", title: "已恢复项目" }] })
    await pending

    expect(document.querySelector(".create-project-form")).not.toBeNull()
    expect(globalThis.state.projects).toEqual([{ id: "restored", title: "已恢复项目" }])
    expect(globalThis.router.refresh).not.toHaveBeenCalled()
    expect(globalThis.api.projects.listDeleted).toHaveBeenCalledTimes(1)
  })

  it.each([
    ["离开项目页", () => document.querySelector(".project-catalog").remove()],
    ["回收站弹窗被替换", () => {
      document.getElementById("modal-body").innerHTML = '<div class="create-project-form"></div>'
    }],
  ])("恢复响应晚到且%s时不再驱动旧界面", async (_label, loseOwner) => {
    document.body.innerHTML = `
      <main id="workspace-content" data-workspace-view="project"><section class="project-catalog"></section></main>
      <div id="modal-body"></div>
    `
    setBridgeOverrides({
      showModalHtml: vi.fn((_title, html) => { document.getElementById("modal-body").innerHTML = html }),
    })
    let resolveRestore
    globalThis.api.projects.restore = vi.fn(() => new Promise((resolve) => { resolveRestore = resolve }))
    await showRecycleBin(0)

    const restoring = document.querySelector('.restore-project-btn[data-id="d1"]').onclick()
    loseOwner()
    resolveRestore({})
    await restoring

    expect(globalThis.api.projects.restore).toHaveBeenCalledWith("d1")
    expect(globalThis.toast).not.toHaveBeenCalled()
    expect(globalThis.router.refresh).not.toHaveBeenCalled()
    expect(globalThis.api.projects.list).not.toHaveBeenCalled()
    expect(globalThis.api.projects.listDeleted).toHaveBeenCalledTimes(1)
  })

  it("批量永久删除需二次确认", async () => {
    stubModal()
    setBridgeOverrides({ confirmAction: (_msg, onConfirm) => onConfirm() })
    globalThis.api.projects.permanentDeleteMany = vi.fn(async () => ({ deleted_count: 2 }))
    await showRecycleBin(0)
    document.getElementById("recycle-select-all").click()
    expect(document.getElementById("recycle-bulk-delete").disabled).toBe(false)
    document.getElementById("recycle-bulk-delete").click()
    await vi.waitFor(() => {
      expect(globalThis.api.projects.permanentDeleteMany).toHaveBeenCalledWith(["d1", "d2"])
    })
    expect(globalThis.toast).toHaveBeenCalledWith("已永久删除 2 部作品", "success")
  })

  it.each([
    ["单个", "single"],
    ["批量", "bulk"],
  ])("%s永久删除成功时先关闭确认框再重开回收站", async (_label, kind) => {
    document.body.innerHTML = `
      <main id="workspace-content"><section class="project-catalog"></section></main>
      <div id="modal-overlay" class="hidden"><div id="modal-body"></div></div>
    `
    globalThis.state.currentView = "project"
    let confirmHandler
    const showModalHtml = vi.fn((_title, html) => {
      document.getElementById("modal-body").innerHTML = html
      document.getElementById("modal-overlay").classList.remove("hidden")
    })
    const closeModal = vi.fn(() => {
      document.getElementById("modal-overlay").classList.add("hidden")
      document.getElementById("modal-body").innerHTML = ""
      return true
    })
    setBridgeOverrides({
      showModalHtml,
      closeModal,
      confirmAction: (_message, onConfirm) => {
        document.getElementById("modal-body").innerHTML = '<p class="confirm-owner"></p>'
        confirmHandler = onConfirm
      },
    })
    if (kind === "bulk") globalThis.api.projects.permanentDeleteMany = vi.fn(async () => ({ deleted_count: 2 }))
    else globalThis.api.projects.permanentDelete = vi.fn(async () => ({}))
    await showRecycleBin(0)

    if (kind === "bulk") {
      document.getElementById("recycle-select-all").click()
      document.getElementById("recycle-bulk-delete").click()
    } else {
      document.querySelector('.perm-delete-project-btn[data-id="d1"]').click()
    }
    await expect(confirmHandler()).resolves.toBe(true)

    expect(closeModal).toHaveBeenCalledTimes(1)
    expect(showModalHtml).toHaveBeenCalledTimes(2)
    expect(closeModal.mock.invocationCallOrder[0]).toBeLessThan(showModalHtml.mock.invocationCallOrder[1])
    expect(document.querySelector(".recycle-bin")).not.toBeNull()
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
  })

  it.each([
    ["单个", "single"],
    ["批量", "bulk"],
  ])("%s永久删除失败晚到且模态已换主时收口旧确认框", async (_label, kind) => {
    const request = deferred()
    let confirmHandler
    globalThis.state.currentView = "project"
    setBridgeOverrides({
      showModalHtml: vi.fn((_title, html) => { document.body.innerHTML = `<div id="modal-body">${html}</div>` }),
      confirmAction: (_message, onConfirm) => {
        document.getElementById("modal-body").innerHTML = '<p class="confirm-owner"></p>'
        confirmHandler = onConfirm
      },
    })
    if (kind === "bulk") globalThis.api.projects.permanentDeleteMany = vi.fn(() => request.promise)
    else globalThis.api.projects.permanentDelete = vi.fn(() => request.promise)
    await showRecycleBin(0)

    if (kind === "bulk") {
      document.getElementById("recycle-select-all").click()
      document.getElementById("recycle-bulk-delete").click()
    } else {
      document.querySelector('.perm-delete-project-btn[data-id="d1"]').click()
    }
    const pending = confirmHandler()
    document.getElementById("modal-body").innerHTML = '<div class="create-project-form"></div>'
    request.reject(new Error("late delete failure"))

    await expect(pending).resolves.toBe(true)
    expect(globalThis.toast).not.toHaveBeenCalledWith(expect.stringContaining("late delete failure"), "error")
    expect(globalThis.api.projects.listDeleted).toHaveBeenCalledTimes(1)
  })

  it.each([
    ["单个", "single", "永久删除失败：delete failure"],
    ["批量", "bulk", "批量永久删除失败：delete failure"],
  ])("%s永久删除当前请求失败时保留确认框", async (_label, kind, message) => {
    let confirmHandler
    globalThis.state.currentView = "project"
    setBridgeOverrides({
      showModalHtml: vi.fn((_title, html) => { document.body.innerHTML = `<div id="modal-body">${html}</div>` }),
      confirmAction: (_message, onConfirm) => {
        document.getElementById("modal-body").innerHTML = '<p class="confirm-owner"></p>'
        confirmHandler = onConfirm
      },
    })
    if (kind === "bulk") globalThis.api.projects.permanentDeleteMany = vi.fn(async () => { throw new Error("delete failure") })
    else globalThis.api.projects.permanentDelete = vi.fn(async () => { throw new Error("delete failure") })
    await showRecycleBin(0)

    if (kind === "bulk") {
      document.getElementById("recycle-select-all").click()
      document.getElementById("recycle-bulk-delete").click()
    } else {
      document.querySelector('.perm-delete-project-btn[data-id="d1"]').click()
    }

    await expect(confirmHandler()).resolves.toBe(false)
    expect(globalThis.toast).toHaveBeenCalledWith(message, "error")
  })

  it("空回收站显示空态且重置分页", async () => {
    globalThis.api.projects.listDeleted = vi.fn(async () => ({ items: [], total: 0 }))
    const showModalHtml = stubModal()
    projectSession.recycleBinSkip = 40
    await showRecycleBin(40)
    expect(showModalHtml).toHaveBeenCalledWith("回收站", expect.stringContaining("回收站为空"), [], { size: "large" })
    expect(projectSession.recycleBinSkip).toBe(0)
  })

  it("skip 超出范围时回退到最后一页", async () => {
    globalThis.api.projects.listDeleted = vi.fn(async (_skip) => ({
      items: [deletedItem("d9")],
      total: 3,
    }))
    stubModal()
    await showRecycleBin(40)
    // 40 >= total=3 → 回退到最后一页 skip=0... total=3 → lastPageSkip = floor(2/20)*20 = 0
    expect(globalThis.api.projects.listDeleted).toHaveBeenLastCalledWith(0, 20)
  })

  it("连续分页逆序返回时只显示最新请求", async () => {
    const pending = new Map()
    globalThis.api.projects.listDeleted = vi.fn((skip) => new Promise((resolve) => pending.set(skip, resolve)))
    const showModalHtml = stubModal()

    const first = showRecycleBin(0)
    const latest = showRecycleBin(20)
    pending.get(20)({ items: [deletedItem("latest")], total: 40 })
    await latest
    pending.get(0)({ items: [deletedItem("stale")], total: 40 })
    await first

    expect(showModalHtml).toHaveBeenCalledTimes(1)
    expect(document.querySelector('.recycle-project-checkbox[data-id="latest"]')).not.toBeNull()
    expect(document.querySelector('.recycle-project-checkbox[data-id="stale"]')).toBeNull()
    expect(projectSession.recycleBinSkip).toBe(20)
  })

  it("关闭回收站后忽略分页的晚到响应", async () => {
    document.body.innerHTML = '<div id="modal-overlay" class="hidden"><div id="modal-body"></div></div>'
    const showModalHtml = vi.fn((_title, html) => {
      document.getElementById("modal-body").innerHTML = html
      document.getElementById("modal-overlay").classList.remove("hidden")
    })
    setBridgeOverrides({ showModalHtml })
    globalThis.api.projects.listDeleted = vi.fn(async () => ({
      items: [deletedItem("page-1")],
      total: 40,
    }))
    await showRecycleBin(0)

    let resolveNext
    globalThis.api.projects.listDeleted = vi.fn(() => new Promise((resolve) => { resolveNext = resolve }))
    const nextPage = showRecycleBin(20)
    document.getElementById("modal-overlay").classList.add("hidden")
    resolveNext({ items: [deletedItem("late")], total: 40 })
    await nextPage

    expect(showModalHtml).toHaveBeenCalledTimes(1)
    expect(document.querySelector('.recycle-project-checkbox[data-id="late"]')).toBeNull()
  })

  it("初次加载期间打开其他弹窗时不覆盖当前弹窗", async () => {
    document.body.innerHTML = '<div id="modal-overlay" class="hidden"><div id="modal-body"></div></div>'
    const showModalHtml = vi.fn()
    setBridgeOverrides({ showModalHtml })
    let resolveLoad
    globalThis.api.projects.listDeleted = vi.fn(() => new Promise((resolve) => { resolveLoad = resolve }))

    const loading = showRecycleBin(0)
    document.getElementById("modal-overlay").classList.remove("hidden")
    document.getElementById("modal-body").innerHTML = '<div class="create-project-form"></div>'
    resolveLoad({ items: [deletedItem("late")], total: 1 })
    await loading

    expect(showModalHtml).not.toHaveBeenCalled()
    expect(document.querySelector(".create-project-form")).not.toBeNull()
  })
})

describe("项目 modal 流程", () => {
  function makeState(projects = [{ id: "p1", title: "星际旅人", genre: "scifi" }], currentProjectId = null) {
    return { projects, currentProjectId, currentProject: null, viewStates: {} }
  }

  it("showCreateForm 渲染创建表单", () => {
    const showModalHtml = vi.fn()
    setBridgeOverrides({ showModalHtml })
    showCreateForm()
    expect(showModalHtml).toHaveBeenCalledWith(
      "新建作品",
      expect.stringContaining("create-title"),
      expect.arrayContaining([expect.objectContaining({ text: "创建" })]),
    )
  })

  it("创建与编辑表单的可见 label 精确关联控件，标题为必填", () => {
    let formHtml = ""
    setBridgeOverrides({
      showModalHtml: (_title, html) => { formHtml = html },
    })

    showCreateForm()
    document.body.innerHTML = formHtml
    for (const id of ["create-title", "create-genre", "create-language", "create-tone"]) {
      expect(document.querySelector(`label[for="${id}"]`)).not.toBeNull()
    }
    expect(document.getElementById("create-title").required).toBe(true)

    const state = makeState()
    setBridgeOverrides({ state })
    editProject("p1")
    document.body.innerHTML = formHtml
    for (const id of ["edit-title", "edit-genre", "edit-tone", "edit-target-length", "edit-stage"]) {
      expect(document.querySelector(`label[for="${id}"]`)).not.toBeNull()
    }
    expect(document.getElementById("edit-title").required).toBe(true)
  })

  it("editProject 保存回写 state 并交由 modal footer 收口", async () => {
    const state = makeState([{ id: "p1", title: "旧标题" }], "p1")
    state.currentProject = { id: "p1", title: "旧标题" }
    const closeModal = vi.fn()
    setBridgeOverrides({ state, closeModal })
    globalThis.api.projects.update = vi.fn(async (_id, payload) => ({ ...payload }))
    let saveHandler = null
    setBridgeOverrides({
      showModalHtml: (title, html, buttons) => {
        document.body.innerHTML = `<div id="modal-body">${html}</div>`
        saveHandler = buttons[0].handler
      },
    })

    editProject("p1")
    document.getElementById("edit-title").value = "  新标题  "
    document.getElementById("edit-genre").value = "fantasy"
    expect(await saveHandler()).toBe(true)

    expect(globalThis.api.projects.update).toHaveBeenCalledWith("p1", expect.objectContaining({ title: "新标题", genre: "fantasy" }))
    expect(state.projects[0].title).toBe("新标题")
    expect(state.currentProject.title).toBe("新标题")
    expect(globalThis.toast).toHaveBeenCalledWith("作品已更新", "success")
    expect(closeModal).not.toHaveBeenCalled()
  })

  it("editProject 响应晚到且弹窗已替换时不回写或提示", async () => {
    const state = makeState([{ id: "p1", title: "旧标题" }], "p1")
    const request = deferred()
    let saveHandler = null
    setBridgeOverrides({
      state,
      showModalHtml: (_title, html, buttons) => {
        document.body.innerHTML = `<div id="modal-body">${html}</div>`
        saveHandler = buttons[0].handler
      },
    })
    globalThis.api.projects.update.mockReturnValue(request.promise)

    editProject("p1")
    document.getElementById("edit-title").value = "新标题"
    const pending = saveHandler()
    document.getElementById("modal-body").innerHTML = '<div class="replacement-modal"></div>'
    request.resolve({ title: "新标题" })

    await expect(pending).resolves.toBe(true)
    expect(state.projects[0].title).toBe("旧标题")
    expect(globalThis.toast).not.toHaveBeenCalled()
  })

  it.each(["", "   "])("editProject 标题为 %j 时保持 modal 并聚焦标题", async (title) => {
    const state = makeState()
    let saveHandler = null
    setBridgeOverrides({
      state,
      showModalHtml: (title, html, buttons) => {
        document.body.innerHTML = `<div id="modal-body">${html}</div>`
        saveHandler = buttons[0].handler
      },
    })
    editProject("p1")
    const titleInput = document.getElementById("edit-title")
    titleInput.value = title
    expect(await saveHandler()).toBe(false)
    expect(globalThis.toast).toHaveBeenCalledWith("请输入作品标题", "warning")
    expect(globalThis.api.projects.update).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(titleInput)
  })

  it("editProject API 失败时保留字段和 state，且不关闭 modal", async () => {
    const state = makeState([{ id: "p1", title: "旧标题", genre: "旧题材", tone: "旧基调" }], "p1")
    state.currentProject = { id: "p1", title: "旧标题", genre: "旧题材", tone: "旧基调" }
    const closeModal = vi.fn()
    let saveHandler = null
    setBridgeOverrides({
      state,
      closeModal,
      showModalHtml: (_title, html, buttons) => {
        document.body.innerHTML = `<div id="modal-body">${html}</div>`
        saveHandler = buttons[0].handler
      },
    })
    globalThis.api.projects.update = vi.fn(async () => { throw new Error("edit test diagnostic") })

    editProject("p1")
    document.getElementById("edit-title").value = "保留标题"
    document.getElementById("edit-genre").value = "保留题材"
    document.getElementById("edit-tone").value = "保留基调"
    expect(await saveHandler()).toBe(false)

    expect(globalThis.api.projects.update).toHaveBeenCalledWith("p1", expect.objectContaining({ title: "保留标题" }))
    expect(document.getElementById("edit-title").value).toBe("保留标题")
    expect(document.getElementById("edit-genre").value).toBe("保留题材")
    expect(document.getElementById("edit-tone").value).toBe("保留基调")
    expect(state.projects[0]).toMatchObject({ title: "旧标题", genre: "旧题材", tone: "旧基调" })
    expect(state.currentProject).toMatchObject({ title: "旧标题", genre: "旧题材", tone: "旧基调" })
    expect(closeModal).not.toHaveBeenCalled()
  })

  it.each(["", "   "])("showCreateForm 标题为 %j 时保持 modal 并聚焦标题", async (title) => {
    const state = makeState()
    let createHandler = null
    setBridgeOverrides({
      state,
      showModalHtml: (_title, html, buttons) => {
        document.body.innerHTML = `<div id="modal-body">${html}</div>`
        createHandler = buttons[0].handler
      },
    })

    showCreateForm()
    const titleInput = document.getElementById("create-title")
    titleInput.value = title
    expect(await createHandler()).toBe(false)
    expect(globalThis.toast).toHaveBeenCalledWith("请输入作品标题", "warning")
    expect(globalThis.api.projects.create).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(titleInput)
  })

  it("showCreateForm 发送 trim 后的标题并保留成功路径", async () => {
    const state = makeState([], null)
    let createHandler = null
    setBridgeOverrides({
      state,
      showModalHtml: (_title, html, buttons) => {
        document.body.innerHTML = `<div id="modal-body">${html}</div>`
        createHandler = buttons[0].handler
      },
    })
    globalThis.api.projects.create = vi.fn(async (payload) => ({ id: "p-created", ...payload }))

    showCreateForm()
    document.getElementById("create-title").value = "  修剪后的标题  "
    document.getElementById("create-genre").value = "fantasy"
    document.getElementById("create-tone").value = "黑暗"
    expect(await createHandler()).toBe(true)

    expect(globalThis.api.projects.create).toHaveBeenCalledWith(expect.objectContaining({ title: "修剪后的标题" }))
    expect(globalThis.toast).toHaveBeenCalledWith("作品「修剪后的标题」已创建", "success")
    expect(state).toMatchObject({ currentProjectId: "p-created", currentProject: { title: "修剪后的标题" } })
    expect(globalThis.router.navigate).toHaveBeenCalledWith("writing")
  })

  it("showCreateForm API 失败时保留所有字段和原 state", async () => {
    const state = makeState([{ id: "p-old", title: "原项目" }], "p-old")
    state.currentProject = { id: "p-old", title: "原项目" }
    let createHandler = null
    setBridgeOverrides({
      state,
      showModalHtml: (_title, html, buttons) => {
        document.body.innerHTML = `<div id="modal-body">${html}</div>`
        createHandler = buttons[0].handler
      },
    })
    globalThis.api.projects.create = vi.fn(async () => { throw new Error("create test diagnostic") })

    showCreateForm()
    document.getElementById("create-title").value = "保留标题"
    document.getElementById("create-genre").value = "mystery"
    document.getElementById("create-tone").value = "悬疑"
    expect(await createHandler()).toBe(false)

    expect(document.getElementById("create-title").value).toBe("保留标题")
    expect(document.getElementById("create-genre").value).toBe("mystery")
    expect(document.getElementById("create-tone").value).toBe("悬疑")
    expect(state).toMatchObject({ currentProjectId: "p-old", currentProject: { title: "原项目" } })
    expect(globalThis.router.navigate).not.toHaveBeenCalled()
  })

  it("deleteProject 确认后删除并在需要时清理当前项目", async () => {
    const state = makeState([{ id: "p1", title: "星际旅人" }], "p1")
    state.currentProject = { id: "p1" }
    setBridgeOverrides({
      state,
      confirmAction: (_msg, onConfirm) => onConfirm(),
    })
    globalThis.api.projects.remove = vi.fn(async () => ({}))
    const clearSelection = vi.fn()

    deleteProject("p1", { clearCurrentProjectSelection: clearSelection })
    await vi.waitFor(() => {
      expect(globalThis.api.projects.remove).toHaveBeenCalledWith("p1")
    })
    expect(globalThis.toast).toHaveBeenCalledWith("作品「星际旅人」已移至回收站", "success")
    expect(clearSelection).toHaveBeenCalled()
    expect(state.projects).toEqual([])
    expect(globalThis.router.refresh).not.toHaveBeenCalled()
  })

  it("deleteProject 当前请求失败时保留确认框", async () => {
    const state = makeState([{ id: "p1", title: "星际旅人" }])
    let confirmDelete = null
    setBridgeOverrides({ state, confirmAction: (_msg, onConfirm) => { confirmDelete = onConfirm } })
    globalThis.api.projects.remove.mockRejectedValue(new Error("delete failed"))

    deleteProject("p1")

    await expect(confirmDelete()).resolves.toBe(false)
    expect(globalThis.toast).toHaveBeenCalledWith("删除失败：delete failed", "error")
    expect(globalThis.router.refresh).not.toHaveBeenCalled()
  })

  it("导入为新项目只在用户确认后创建项目并上传文件", async () => {
    const state = makeState()
    let confirmImport = null
    const confirmAction = vi.fn((_message, onConfirm) => { confirmImport = onConfirm })
    setBridgeOverrides({ state, confirmAction })
    globalThis.api.projects.create.mockResolvedValue({ id: "p-new", title: "迷雾之城" })
    globalThis.api.projects.list.mockResolvedValue({ items: [{ id: "p-new", title: "迷雾之城" }] })
    globalThis.api.imports.uploadFile.mockResolvedValue({ total_chapters: 12, imported_chapters: 12 })

    const createElement = document.createElement.bind(document)
    let fileInput = null
    const createSpy = vi.spyOn(document, "createElement").mockImplementation((tagName, options) => {
      const element = createElement(tagName, options)
      if (String(tagName).toLowerCase() === "input") fileInput = element
      return element
    })
    try {
      importAsNewProject()
      const file = new File(["正文"], "迷雾之城.txt", { type: "text/plain" })
      Object.defineProperty(fileInput, "files", { configurable: true, value: [file] })
      await fileInput.onchange()

      expect(confirmAction).toHaveBeenCalledWith(
        "将创建新作品「迷雾之城」并导入文件「迷雾之城.txt」。是否继续？",
        expect.any(Function),
        "创建并导入",
      )
      expect(globalThis.api.projects.create).not.toHaveBeenCalled()

      await confirmImport()
      expect(globalThis.api.projects.create).toHaveBeenCalledWith(expect.objectContaining({ title: "迷雾之城" }))
      expect(globalThis.api.imports.uploadFile).toHaveBeenCalledWith(file, "p-new")
      expect(state).toMatchObject({ currentProjectId: "p-new", currentProject: { id: "p-new" } })
      expect(globalThis.router.navigate).toHaveBeenCalledWith("writing")
    } finally {
      createSpy.mockRestore()
    }
  })

  it("传入已有 File 时不创建 chooser，并复用同一文件完成创建上传", async () => {
    const state = makeState()
    let confirmImport = null
    setBridgeOverrides({ state, confirmAction: (_message, onConfirm) => { confirmImport = onConfirm } })
    globalThis.api.projects.create.mockResolvedValue({ id: "p-direct", title: "直传文件" })
    globalThis.api.projects.list.mockResolvedValue({ items: [{ id: "p-direct", title: "直传文件" }] })
    globalThis.api.imports.uploadFile.mockResolvedValue({ total_chapters: 2, imported_chapters: 2 })
    const createSpy = vi.spyOn(document, "createElement")
    const file = new File(["正文"], "直传文件.txt", { type: "text/plain" })

    try {
      importAsNewProject(file)

      expect(createSpy).not.toHaveBeenCalled()
      expect(confirmImport).toBeTypeOf("function")
      await confirmImport()
      expect(globalThis.api.projects.create).toHaveBeenCalledWith(expect.objectContaining({ title: "直传文件" }))
      expect(globalThis.api.imports.uploadFile).toHaveBeenCalledWith(file, "p-direct")
    } finally {
      createSpy.mockRestore()
    }
  })

  it("无参导入只打开一次既有 chooser", () => {
    const createElement = document.createElement.bind(document)
    let chooser = null
    let chooserClick = null
    const createSpy = vi.spyOn(document, "createElement").mockImplementation((tagName, options) => {
      const element = createElement(tagName, options)
      if (String(tagName).toLowerCase() === "input") {
        chooser = element
        chooserClick = vi.spyOn(element, "click")
      }
      return element
    })
    try {
      importAsNewProject()

      expect(chooser).not.toBeNull()
      expect(chooser.accept).toBe(".txt,.epub,.html,.htm")
      expect(chooserClick).toHaveBeenCalledTimes(1)
    } finally {
      createSpy.mockRestore()
    }
  })

  it("传入无效 File 时仅显示既有校验错误，不打开 chooser或创建项目", () => {
    const confirmAction = vi.fn()
    setBridgeOverrides({ confirmAction })
    const createSpy = vi.spyOn(document, "createElement")
    const invalidFile = new File(["正文"], "不支持.pdf", { type: "application/pdf" })
    try {
      importAsNewProject(invalidFile)

      expect(createSpy).not.toHaveBeenCalled()
      expect(globalThis.toast).toHaveBeenCalledWith(
        "不支持的文件格式，请选择 txt、epub、html 或 htm 文件",
        "error",
      )
      expect(confirmAction).not.toHaveBeenCalled()
      expect(globalThis.api.projects.create).not.toHaveBeenCalled()
    } finally {
      createSpy.mockRestore()
    }
  })

  it("上传前拦截不支持的格式且不创建项目", async () => {
    const state = makeState()
    const confirmAction = vi.fn()
    setBridgeOverrides({ state, confirmAction })
    const createElement = document.createElement.bind(document)
    let fileInput = null
    const createSpy = vi.spyOn(document, "createElement").mockImplementation((tagName, options) => {
      const element = createElement(tagName, options)
      if (String(tagName).toLowerCase() === "input") fileInput = element
      return element
    })
    try {
      importAsNewProject()
      Object.defineProperty(fileInput, "files", { configurable: true, value: [new File(["正文"], "错误格式.pdf")] })
      await fileInput.onchange()
      expect(globalThis.toast).toHaveBeenCalledWith(
        "不支持的文件格式，请选择 txt、epub、html 或 htm 文件",
        "error",
      )
      expect(confirmAction).not.toHaveBeenCalled()
      expect(globalThis.api.projects.create).not.toHaveBeenCalled()

      const tooLarge = new File(["正文"], "超限.txt")
      Object.defineProperty(tooLarge, "size", { configurable: true, value: 50 * 1024 * 1024 + 1 })
      Object.defineProperty(fileInput, "files", { configurable: true, value: [tooLarge] })
      await fileInput.onchange()
      expect(globalThis.toast).toHaveBeenCalledWith("文件大小超过限制（最大 50MB）", "error")
      expect(confirmAction).not.toHaveBeenCalled()
      expect(globalThis.api.projects.create).not.toHaveBeenCalled()
    } finally {
      createSpy.mockRestore()
    }
  })

  it("新项目导入失败时保留并选中新项目供重试", async () => {
    const state = makeState([{ id: "p-old", title: "原项目" }], "p-old")
    state.currentProject = { id: "p-old", title: "原项目" }
    let confirmImport = null
    setBridgeOverrides({ state, confirmAction: (_message, onConfirm) => { confirmImport = onConfirm } })
    globalThis.api.projects.create.mockResolvedValue({ id: "p-new", title: "失败导入" })
    globalThis.api.projects.list.mockResolvedValue({ items: [{ id: "p-old" }, { id: "p-new" }] })
    globalThis.api.imports.uploadFile.mockRejectedValue(new Error("解析失败"))
    const createElement = document.createElement.bind(document)
    let fileInput = null
    const createSpy = vi.spyOn(document, "createElement").mockImplementation((tagName, options) => {
      const element = createElement(tagName, options)
      if (String(tagName).toLowerCase() === "input") fileInput = element
      return element
    })
    try {
      importAsNewProject()
      Object.defineProperty(fileInput, "files", { configurable: true, value: [new File(["正文"], "失败导入.txt")] })
      await fileInput.onchange()
      await confirmImport()
      expect(state.currentProjectId).toBe("p-new")
      expect(state.currentProject.id).toBe("p-new")
      expect(state.projects.map((project) => project.id)).toEqual(["p-old", "p-new"])
      expect(globalThis.toast).toHaveBeenCalledWith(
        "导入失败：解析失败。作品「失败导入」已保留并选中，可在作品页重新导入文件",
        "error",
      )
      expect(globalThis.router.navigate).toHaveBeenCalledWith("project")
      expect(globalThis.router.navigate).not.toHaveBeenCalledWith("writing")
    } finally {
      createSpy.mockRestore()
    }
  })

  it("上传期间用户切换项目时不抢回新建项目", async () => {
    const state = makeState()
    state.currentProjectId = "p-old"
    state.currentProject = { id: "p-old" }
    let confirmImport = null
    let resolveUpload = null
    setBridgeOverrides({ state, confirmAction: (_message, onConfirm) => { confirmImport = onConfirm } })
    globalThis.api.projects.create.mockResolvedValue({ id: "p-import", title: "慢导入" })
    globalThis.api.projects.list.mockResolvedValue({ items: [{ id: "p-old" }, { id: "p-import" }] })
    globalThis.api.imports.uploadFile.mockImplementation(() => new Promise((resolve) => { resolveUpload = resolve }))
    const createElement = document.createElement.bind(document)
    let fileInput = null
    const createSpy = vi.spyOn(document, "createElement").mockImplementation((tagName, options) => {
      const element = createElement(tagName, options)
      if (String(tagName).toLowerCase() === "input") fileInput = element
      return element
    })
    try {
      importAsNewProject()
      Object.defineProperty(fileInput, "files", { configurable: true, value: [new File(["正文"], "慢导入.txt")] })
      await fileInput.onchange()
      const pending = confirmImport()
      await vi.waitFor(() => expect(resolveUpload).toBeTypeOf("function"))
      state.currentProjectId = "p-user-selected"
      state.currentProject = { id: "p-user-selected" }
      resolveUpload({ total_chapters: 1, imported_chapters: 1 })
      await pending
      expect(state.currentProjectId).toBe("p-user-selected")
      expect(globalThis.router.navigate).not.toHaveBeenCalledWith("writing")
    } finally {
      createSpy.mockRestore()
    }
  })

  it("上传期间弹窗被替换时只完成已发起的导入", async () => {
    const state = { ...makeState([], null), currentView: "project" }
    const upload = deferred()
    let confirmImport = null
    document.body.innerHTML = '<div id="modal-body"><p class="confirm-owner"></p></div>'
    setBridgeOverrides({ state, confirmAction: (_message, onConfirm) => { confirmImport = onConfirm } })
    globalThis.api.projects.create.mockResolvedValue({ id: "p-import", title: "慢导入" })
    globalThis.api.imports.uploadFile.mockReturnValue(upload.promise)
    const file = new File(["正文"], "慢导入.txt", { type: "text/plain" })

    importAsNewProject(file)
    const pending = confirmImport()
    await vi.waitFor(() => expect(globalThis.api.imports.uploadFile).toHaveBeenCalledWith(file, "p-import"))
    expect(state.currentProjectId).toBe("p-import")
    document.getElementById("modal-body").innerHTML = '<div class="replacement-modal"></div>'
    upload.resolve({ total_chapters: 1, imported_chapters: 1 })

    await expect(pending).resolves.toBe(true)
    expect(state.currentProjectId).toBe("p-import")
    expect(globalThis.toast).not.toHaveBeenCalled()
    expect(globalThis.router.navigate).not.toHaveBeenCalled()
  })
})
