/**
 * writingView 测试 — 核心生命周期和行为
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import writingView from "../views/writingView.js"

beforeEach(() => {
  state.currentProjectId = null
  state.currentProject = null
  state.viewStates = {}
  vi.clearAllMocks()
})

describe("render", () => {
  it("loading 状态显示加载中", async () => {
    writingView._loading = true
    const html = await writingView.render()
    expect(html).toContain("加载中")
  })

  it("无章节时显示空状态", async () => {
    writingView._loading = false
    writingView._chapterList = []
    const html = await writingView.render()
    expect(html).toContain("开始创作")
  })

  it("有章节时渲染编辑器", async () => {
    writingView._loading = false
    writingView._chapterList = [1]
    writingView._currentChapter = 1
    writingView._chapters = { 1: { draftCount: 0 } }
    writingView._scenes = []
    writingView._versions = []
    const html = await writingView.render()
    expect(html).toContain("Scene 树")
    expect(html).toContain("writing-editor")
  })
})

describe("onEnter", () => {
  it("无项目时 loading=false", async () => {
    await writingView.onEnter()
    expect(writingView._loading).toBe(false)
  })

  it("有项目时加载数据", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({ chapter_indices: [1, 3] })
    api.outline.listScenesOrdered.mockResolvedValue([])
    await writingView.onEnter()
    expect(writingView._chapterList).toEqual([1, 3])
    expect(writingView._chapters[1]).toBeDefined()
  })

  it("API 失败时降级为空列表", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockRejectedValue(new Error("fail"))
    await writingView.onEnter()
    expect(writingView._chapterList).toEqual([])
  })
})

describe("onLeave", () => {
  it("保存编辑状态", () => {
    writingView._currentChapter = 2
    writingView._currentTitle = "title"
    writingView.onLeave()
    expect(state.viewStates.writing.currentChapter).toBe(2)
    expect(state.viewStates.writing.currentTitle).toBe("title")
  })
})

describe("_findCurrentScene", () => {
  it("通过 chapter_ids 匹配", () => {
    writingView._currentChapter = 2
    writingView._scenes = [
      { id: "s1", chapter_ids: ["1"] },
      { id: "s2", chapter_ids: ["2"] },
    ]
    expect(writingView._findCurrentScene()?.id).toBe("s2")
  })

  it("无匹配返回 null", () => {
    writingView._currentChapter = 99
    writingView._scenes = [{ id: "s1", chapter_ids: ["1"] }]
    expect(writingView._findCurrentScene()).toBeNull()
  })
})

describe("_bindEvents", () => {
  it("autosave 按钮触发 _autosave", () => {
    const spy = vi.spyOn(writingView, "_autosave").mockImplementation(() => {})
    document.body.innerHTML = '<div id="workspace-content"><button data-action="autosave">x</button></div>'
    writingView._bindEvents()
    document.querySelector("#workspace-content button").click()
    expect(spy).toHaveBeenCalled()
    spy.mockRestore()
  })
})

describe("_submitDeepImport", () => {
  it("重复导入需要确认时，确认后使用 force=true 重新提交", async () => {
    state.currentProjectId = "p1"
    api.imports.deepImport
      .mockResolvedValueOnce({
        status: "requires_confirmation",
        requires_confirmation: true,
        warning: "第 1-5 章已有数据。重新导入将覆盖现有数据。是否继续？",
      })
      .mockResolvedValueOnce({
        task_id: "task-2",
        status: "pending",
        requires_confirmation: false,
      })
    confirmAction.mockImplementation((_message, onConfirm) => onConfirm())
    const pollingSpy = vi
      .spyOn(writingView, "_startDeepImportPolling")
      .mockImplementation(() => {})

    await writingView._submitDeepImport(1, 5)

    expect(api.imports.deepImport).toHaveBeenNthCalledWith(1, "p1", 1, 5, false)
    expect(api.imports.deepImport).toHaveBeenNthCalledWith(2, "p1", 1, 5, true)
    expect(writingView._deepImportTaskId).toBe("task-2")
    expect(writingView._deepImportProgress.phase).toBe("running")
    expect(pollingSpy).toHaveBeenCalled()

    pollingSpy.mockRestore()
  })
})
