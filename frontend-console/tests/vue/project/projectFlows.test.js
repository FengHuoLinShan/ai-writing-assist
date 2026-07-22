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
    expect(document.getElementById("recycle-prev-page").disabled).toBe(true)
    expect(document.getElementById("recycle-next-page").disabled).toBe(true)
  })

  it("恢复项目后刷新背景列表并重载回收站", async () => {
    stubModal()
    globalThis.api.projects.restore = vi.fn(async () => ({}))
    await showRecycleBin(0)
    await document.querySelector('.restore-project-btn[data-id="d1"]').click()
    await vi.waitFor(() => {
      expect(globalThis.api.projects.restore).toHaveBeenCalledWith("d1")
    })
    expect(globalThis.toast).toHaveBeenCalledWith("项目已恢复", "success")
    expect(globalThis.router.refresh).toHaveBeenCalled()
    expect(globalThis.api.projects.listDeleted).toHaveBeenCalledTimes(2)
  })

  it("批量永久删除需二次确认", async () => {
    stubModal()
    setBridgeOverrides({ confirmAction: (_msg, onConfirm) => onConfirm() })
    globalThis.api.projects.permanentDeleteMany = vi.fn(async () => ({ deleted_count: 2 }))
    await showRecycleBin(0)
    document.getElementById("recycle-select-all").click()
    document.getElementById("recycle-bulk-delete").click()
    await vi.waitFor(() => {
      expect(globalThis.api.projects.permanentDeleteMany).toHaveBeenCalledWith(["d1", "d2"])
    })
    expect(globalThis.toast).toHaveBeenCalledWith("已永久删除 2 个项目", "success")
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
    globalThis.api.projects.listDeleted = vi.fn(async (skip) => ({
      items: [deletedItem("d9")],
      total: 3,
    }))
    stubModal()
    await showRecycleBin(40)
    // 40 >= total=3 → 回退到最后一页 skip=0... total=3 → lastPageSkip = floor(2/20)*20 = 0
    expect(globalThis.api.projects.listDeleted).toHaveBeenLastCalledWith(0, 20)
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
      "新建项目",
      expect.stringContaining("create-title"),
      expect.arrayContaining([expect.objectContaining({ text: "创建" })]),
    )
  })

  it("editProject 保存回写 state 并关闭 modal", async () => {
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
    document.getElementById("edit-title").value = "新标题"
    document.getElementById("edit-genre").value = "fantasy"
    await saveHandler()

    expect(globalThis.api.projects.update).toHaveBeenCalledWith("p1", expect.objectContaining({ title: "新标题", genre: "fantasy" }))
    expect(state.projects[0].title).toBe("新标题")
    expect(state.currentProject.title).toBe("新标题")
    expect(globalThis.toast).toHaveBeenCalledWith("项目已更新", "success")
    expect(closeModal).toHaveBeenCalled()
  })

  it("editProject 空标题仅警告", async () => {
    const state = makeState()
    setBridgeOverrides({
      state,
      showModalHtml: (title, html, buttons) => {
        document.body.innerHTML = `<div id="modal-body">${html}</div>`
        globalThis.__saveHandler = buttons[0].handler
      },
    })
    editProject("p1")
    document.getElementById("edit-title").value = ""
    await globalThis.__saveHandler()
    expect(globalThis.toast).toHaveBeenCalledWith("请输入项目标题", "warning")
    expect(globalThis.api.projects.update).not.toHaveBeenCalled()
    delete globalThis.__saveHandler
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
    expect(globalThis.toast).toHaveBeenCalledWith("项目「星际旅人」已移至回收站", "success")
    expect(clearSelection).toHaveBeenCalled()
    expect(globalThis.router.refresh).toHaveBeenCalled()
  })

  it("导入为新项目只在用户确认后创建项目并上传文件", async () => {
    const state = makeState()
    let confirmImport = null
    const confirmAction = vi.fn((_message, onConfirm) => { confirmImport = onConfirm })
    setBridgeOverrides({ state, confirmAction })
    globalThis.api.projects.create.mockResolvedValue({ id: "p-new", title: "迷雾之城" })
    globalThis.api.projects.list.mockResolvedValue({ items: [{ id: "p-new", title: "迷雾之城" }] })
    globalThis.api.imports.upload.mockResolvedValue({ total_chapters: 12, imported_chapters: 12 })

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
        "将创建新项目「迷雾之城」并导入文件「迷雾之城.txt」。是否继续？",
        expect.any(Function),
        "创建并导入",
      )
      expect(globalThis.api.projects.create).not.toHaveBeenCalled()

      await confirmImport()
      expect(globalThis.api.projects.create).toHaveBeenCalledWith(expect.objectContaining({ title: "迷雾之城" }))
      expect(globalThis.api.imports.upload).toHaveBeenCalledWith("p-new", file)
      expect(state).toMatchObject({ currentProjectId: "p-new", currentProject: { id: "p-new" } })
      expect(globalThis.router.navigate).toHaveBeenCalledWith("writing")
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
        "不支持的文件格式，请选择 txt、epub、html、htm、mobi 或 azw3 文件",
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
    globalThis.api.imports.upload.mockRejectedValue(new Error("解析失败"))
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
        "导入失败：解析失败。项目「失败导入」已保留并选中，可在项目页重新导入文件",
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
    globalThis.api.imports.upload.mockImplementation(() => new Promise((resolve) => { resolveUpload = resolve }))
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
})
