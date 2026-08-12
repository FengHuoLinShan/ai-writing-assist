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
      discard: vi.fn(),
      adoptDraftCandidate: vi.fn(),
      deleteDraft: vi.fn(),
    },
    ...overrides.api,
  }
  const toast = vi.fn()
  const onVersionChanged = vi.fn()
  const controller = createEditorController({
    api,
    toast,
    confirm: vi.fn(() => true),
    getProjectId: () => projectId,
    getScenes: () => [],
    onChange: vi.fn(),
    onSceneChange: vi.fn(),
    onVersionChanged,
  })
  return { controller, api, toast, onVersionChanged, setProject: (value) => { projectId = value } }
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

  it("保存新版本晚到时接收新版本元数据但不覆盖随后输入", async () => {
    const late = deferred()
    const { controller, api, toast, onVersionChanged } = makeController()
    api.writing.checkpoint.mockReturnValue(late.promise)
    await controller.loadChapter(1)
    document.body.innerHTML = '<input id="title"><textarea id="body"></textarea>'
    const editor = document.getElementById("body")
    controller.attach({ title: document.getElementById("title"), editor })
    editor.value = "准备留版"
    editor.dispatchEvent(new Event("input"))
    const checkpoint = controller.checkpoint()
    await vi.waitFor(() => expect(api.writing.checkpoint).toHaveBeenCalled())
    expect(controller.snapshot().saving).toBe(true)
    await controller.autosave()
    expect(api.writing.autosave).not.toHaveBeenCalled()

    editor.value = "留版后的新输入"
    editor.dispatchEvent(new Event("input"))
    late.resolve({ id: "d2", title: "第一章", content: "准备留版", version_number: 2, status: "draft", updated_at: "2026-08-12T10:00:00Z" })

    expect(await checkpoint).toMatchObject({ id: "d2", version_number: 2 })
    expect(controller.snapshot()).toMatchObject({ draftId: "d2", versionNumber: 2, updatedAt: "2026-08-12T10:00:00Z", content: "留版后的新输入", dirty: true })
    expect(localStorage.getItem("draft_backup_p1_1")).toContain("留版后的新输入")
    expect(toast).toHaveBeenCalledWith("已保存为新版本；之后的输入仍待保存", "success")
    expect(onVersionChanged).toHaveBeenCalledWith(expect.objectContaining({ id: "d2" }))
    expect(controller.snapshot().saving).toBe(false)
    api.writing.autosave.mockResolvedValueOnce({ id: "d2", title: "第一章", content: "留版后的新输入", version_number: 3, status: "draft" })
    await controller.autosave()
    expect(api.writing.autosave).toHaveBeenCalledWith("d2", expect.objectContaining({ expected_version: 2 }), "p1")
    controller.dispose()
  })

  it("版本列表刷新失败时不把已成功留版误报为保存失败", async () => {
    const { controller, api, toast, onVersionChanged } = makeController()
    api.writing.checkpoint.mockResolvedValue({ id: "d2", title: "第一章", content: "新正文", version_number: 2, status: "draft" })
    onVersionChanged.mockRejectedValue(new Error("list failed"))
    await controller.loadChapter(1)
    controller.setState({ content: "新正文" })

    await expect(controller.checkpoint()).resolves.toMatchObject({ id: "d2" })
    expect(toast).toHaveBeenCalledWith("已保存为新版本", "success")
    expect(toast).toHaveBeenCalledWith("操作已完成，但版本列表暂时未刷新", "warning")
    expect(toast).not.toHaveBeenCalledWith("list failed", "error")
    controller.dispose()
  })

  it("放弃结果晚到时接收基线元数据但不覆盖随后输入", async () => {
    const late = deferred()
    const { controller, api, toast, onVersionChanged } = makeController()
    api.writing.discard.mockReturnValue(late.promise)
    await controller.loadChapter(1)
    document.body.innerHTML = '<input id="title"><textarea id="body"></textarea>'
    const editor = document.getElementById("body")
    controller.attach({ title: document.getElementById("title"), editor })
    const discarding = controller.discardChanges()
    await vi.waitFor(() => expect(api.writing.discard).toHaveBeenCalled())

    editor.value = "回退期间的新输入"
    editor.dispatchEvent(new Event("input"))
    late.resolve({ id: "base", title: "旧基线", content: "旧基线正文", version_number: 1, status: "published", updated_at: "2026-08-12T09:00:00Z" })

    expect(await discarding).toMatchObject({ id: "base" })
    expect(controller.snapshot()).toMatchObject({ draftId: "base", versionNumber: 1, content: "回退期间的新输入", lastSavedContent: "旧基线正文", dirty: true })
    expect(toast).toHaveBeenCalledWith("已回到上一版；之后的输入仍待保存", "success")
    expect(onVersionChanged).toHaveBeenCalledWith(expect.objectContaining({ id: "base" }))
    api.writing.autosave.mockResolvedValueOnce({ id: "next", title: "旧基线", content: "回退期间的新输入", version_number: 2, status: "draft" })
    await controller.autosave()
    expect(api.writing.autosave).toHaveBeenCalledWith("base", expect.objectContaining({ expected_version: 1 }), "p1")
    controller.dispose()
  })

  it("切换章节后放弃更改的晚到结果不覆盖新章节", async () => {
    const late = deferred()
    const { controller, api, toast, onVersionChanged } = makeController()
    api.writing.discard.mockReturnValue(late.promise)
    await controller.loadChapter(1)
    const discarding = controller.discardChanges()
    await vi.waitFor(() => expect(api.writing.discard).toHaveBeenCalled())
    await controller.loadChapter(2)
    late.resolve({ id: "base", title: "旧基线", content: "旧基线正文", version_number: 1, status: "published" })

    expect(await discarding).toBeNull()
    expect(controller.snapshot()).toMatchObject({ chapter: 2, draftId: "d1", content: "原文" })
    expect(toast).not.toHaveBeenCalledWith("已回到上一版", "success")
    expect(onVersionChanged).not.toHaveBeenCalled()
    controller.dispose()
  })

  it("切换章节后采用建议的晚到结果不覆盖新章节", async () => {
    const late = deferred()
    const { controller, api, toast } = makeController()
    api.writing.get.mockResolvedValueOnce({ id: "candidate", novel_id: "p1", title: "建议", content: "建议正文", version_number: 2, status: "candidate" })
    api.writing.adoptDraftCandidate.mockReturnValue(late.promise)
    await controller.loadChapter(1, { draftId: "candidate" })
    const adopting = controller.adoptCandidate()
    await vi.waitFor(() => expect(api.writing.adoptDraftCandidate).toHaveBeenCalled())
    await controller.loadChapter(2)
    late.resolve({ draft: { id: "adopted", title: "建议", content: "建议正文", version_number: 3, status: "draft" } })

    expect(await adopting).toBeNull()
    expect(controller.snapshot()).toMatchObject({ chapter: 2, draftId: "d1", content: "原文" })
    expect(toast).not.toHaveBeenCalledWith("已采用到工作稿", "success")
    controller.dispose()
  })

  it("dispose 后拒绝建议的晚到结果不再反馈成功", async () => {
    const late = deferred()
    const { controller, api, toast } = makeController()
    api.writing.get.mockResolvedValueOnce({ id: "candidate", novel_id: "p1", title: "建议", content: "建议正文", version_number: 2, status: "candidate" })
    api.writing.deleteDraft.mockReturnValue(late.promise)
    await controller.loadChapter(1, { draftId: "candidate" })
    const rejecting = controller.rejectCandidate()
    await vi.waitFor(() => expect(api.writing.deleteDraft).toHaveBeenCalled())
    controller.dispose()
    late.resolve({ ok: true })

    expect(await rejecting).toBe(false)
    expect(toast).not.toHaveBeenCalledWith("已拒绝 AI 建议", "success")
  })
})
