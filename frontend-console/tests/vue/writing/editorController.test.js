import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createEditorController } from "../../../vue/views/writing/controllers/editorController.js"
import { clearWritingSession, readChapterSnapshot } from "../../../vue/views/writing/writingSession.js"

function deferred() {
  let resolve
  const promise = new Promise((next) => { resolve = next })
  return { promise, resolve }
}

function makeController(overrides = {}) {
  let projectId = "p1"
  const api = {
    writing: {
      getVersionHistory: vi.fn(async () => ({ versions: [{ id: "d1", version_number: 1 }] })),
      get: vi.fn(async () => ({ id: "d1", novel_id: projectId, title: "第一章", content: "原文", version_number: 1, status: "draft" })),
      autosave: vi.fn(async (_id, payload) => ({ id: "d1", ...payload, version_number: 2, status: "draft" })),
      autosaveDraftOnly: vi.fn(async (payload) => ({ id: "d-new", ...payload, version_number: 1, status: "draft" })),
      checkpoint: vi.fn(),
      adoptDraftCandidate: vi.fn(),
      deleteDraft: vi.fn(),
    },
    ...overrides.api,
  }
  const toast = vi.fn()
  const controller = createEditorController({
    api,
    toast,
    confirm: vi.fn(() => true),
    getProjectId: () => projectId,
    getScenes: () => [],
    onChange: vi.fn(),
    onSceneChange: vi.fn(),
  })
  return { controller, api, toast, setProject: (value) => { projectId = value } }
}

describe("editorController", () => {
  beforeEach(() => {
    localStorage.clear()
    clearWritingSession()
  })
  afterEach(() => vi.useRealTimers())

  it("只通过显式 element refs 读写编辑器并保存 project/chapter session", async () => {
    const { controller } = makeController()
    await controller.loadChapter(1)
    document.body.innerHTML = '<input id="title"><textarea id="body"></textarea>'
    const title = document.getElementById("title")
    const editor = document.getElementById("body")
    controller.attach({ title, editor })

    editor.value = "本地修改"
    editor.dispatchEvent(new Event("input"))

    expect(controller.snapshot()).toMatchObject({ content: "本地修改", dirty: true })
    expect(readChapterSnapshot("p1", 1)).toMatchObject({ content: "本地修改", dirty: true })
    expect(localStorage.getItem("draft_backup_p1_1")).toContain("本地修改")
    controller.dispose()
  })

  it("项目切换后丢弃旧项目晚到的 draft 响应", async () => {
    const late = deferred()
    const api = {
      writing: {
        getVersionHistory: vi.fn(async () => ({ versions: [{ id: "d1", version_number: 1 }] })),
        get: vi.fn(() => late.promise),
        autosave: vi.fn(),
      },
    }
    const { controller, setProject } = makeController({ api })
    const loading = controller.loadChapter(1)
    await vi.waitFor(() => expect(api.writing.get).toHaveBeenCalled())
    setProject("p2")
    late.resolve({ id: "d1", novel_id: "p1", content: "旧项目正文", title: "旧项目" })

    expect(await loading).toBe(false)
    expect(controller.snapshot().content).toBe("")
    controller.dispose()
  })

  it("加载期间的移动输入不覆盖服务器草稿身份", async () => {
    const late = deferred()
    const { controller, api } = makeController()
    api.writing.get.mockReturnValue(late.promise)
    const loading = controller.loadChapter(1)
    await vi.waitFor(() => expect(api.writing.get).toHaveBeenCalled())
    document.body.innerHTML = '<textarea id="body"></textarea>'
    const editor = document.getElementById("body")
    controller.attach({ title: null, editor })
    editor.value = "请求期间输入"
    editor.dispatchEvent(new Event("input"))

    late.resolve({ id: "d1", novel_id: "p1", title: "第一章", content: "服务器正文", version_number: 1, status: "draft" })
    await loading

    expect(controller.snapshot()).toMatchObject({
      draftId: "d1",
      title: "第一章",
      content: "请求期间输入",
      lastSavedContent: "服务器正文",
      dirty: true,
    })
    await controller.autosave()
    expect(api.writing.autosave).toHaveBeenCalledWith(
      "d1",
      expect.objectContaining({ content: "请求期间输入" }),
      "p1",
    )
    controller.dispose()
  })

  it("保存进行中再次编辑会串行提交第二次暂存", async () => {
    const first = deferred()
    const second = deferred()
    const { controller, api } = makeController()
    api.writing.autosave
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise)
    await controller.loadChapter(1)
    document.body.innerHTML = '<input id="title"><textarea id="body"></textarea>'
    const title = document.getElementById("title")
    const editor = document.getElementById("body")
    controller.attach({ title, editor })
    editor.value = "第一次"
    editor.dispatchEvent(new Event("input"))
    const saveOne = controller.autosave()
    editor.value = "第二次"
    editor.dispatchEvent(new Event("input"))
    const saveTwo = controller.autosave()
    first.resolve({ id: "d1", version_number: 2, status: "draft" })
    await vi.waitFor(() => expect(api.writing.autosave).toHaveBeenCalledTimes(2))
    second.resolve({ id: "d1", version_number: 3, status: "draft" })
    await Promise.all([saveOne, saveTwo])

    expect(api.writing.autosave).toHaveBeenLastCalledWith(
      "d1",
      expect.objectContaining({ content: "第二次", expected_version: 2 }),
      "p1",
    )
    expect(controller.snapshot()).toMatchObject({ content: "第二次", dirty: false })
    controller.dispose()
  })

  it("允许移动速记沿用保存流程并给出明确的工作稿反馈", async () => {
    const { controller, toast } = makeController()
    await controller.loadChapter(1)
    document.body.innerHTML = '<input id="title"><textarea id="body"></textarea>'
    const editor = document.getElementById("body")
    controller.attach({ title: document.getElementById("title"), editor })
    editor.value = "移动速记"
    editor.dispatchEvent(new Event("input"))

    await controller.autosave({ successMessage: "已保存到工作稿" })

    expect(toast).toHaveBeenCalledWith("已保存到工作稿", "success")
    controller.dispose()
  })

  it("移动速记可为尚无草稿的章节创建工作稿", async () => {
    const { controller, api, toast } = makeController()
    api.writing.getVersionHistory.mockResolvedValue({ versions: [] })
    await controller.loadChapter(2)
    document.body.innerHTML = '<textarea id="body"></textarea>'
    const editor = document.getElementById("body")
    controller.attach({ title: null, editor })
    editor.value = "首份移动工作稿"
    editor.dispatchEvent(new Event("input"))

    await controller.autosave({ successMessage: "已保存到工作稿", createIfMissing: true })

    expect(api.writing.autosaveDraftOnly).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      chapter_index: 2,
      content: "首份移动工作稿",
    }))
    expect(controller.snapshot()).toMatchObject({ draftId: "d-new", dirty: false })
    expect(toast).toHaveBeenCalledWith("已保存到工作稿", "success")
    controller.dispose()
  })

  it("dispose 后在途保存不回写 controller", async () => {
    const late = deferred()
    const { controller, api } = makeController()
    api.writing.autosave.mockReturnValue(late.promise)
    await controller.loadChapter(1)
    document.body.innerHTML = '<input id="title"><textarea id="body"></textarea>'
    const editor = document.getElementById("body")
    controller.attach({ title: document.getElementById("title"), editor })
    editor.value = "离开前输入"
    editor.dispatchEvent(new Event("input"))
    const saving = controller.autosave()
    controller.dispose()
    late.resolve({ id: "new-id", version_number: 99, status: "draft" })
    await saving
    expect(controller.snapshot().draftId).toBe("d1")
  })
})
