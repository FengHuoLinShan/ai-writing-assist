/**
 * writingView 测试 — 核心生命周期和行为
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import writingView from "../views/writingView.js"

beforeEach(() => {
  state.currentProjectId = null
  state.currentProject = null
  state.viewStates = {}
  document.body.innerHTML = ""
  writingView._chapters = {}
  writingView._chapterList = []
  writingView._currentChapter = null
  writingView._currentDraftId = null
  writingView._currentContent = null
  writingView._currentTitle = null
  writingView._currentVersionNumber = null
  writingView._versions = []
  writingView._scenes = []
  writingView._currentSceneId = null
  writingView._cursorOffset = 0
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

  it("selects the scene matching the editor cursor offset", () => {
    writingView._currentChapter = 5
    writingView._cursorOffset = 1700
    writingView._scenes = [
      { id: "s1", title: "前段", scene_chunks: [{ chapter_index: 5, start_pos: 0, end_pos: 1500 }] },
      { id: "s2", title: "后段", scene_chunks: [{ chapter_index: 5, start_pos: 1500, end_pos: 3000 }] },
    ]

    expect(writingView._findCurrentScene()?.id).toBe("s2")
  })

  it("prefers offset match over chapter_ids and scene_chunks", () => {
    writingView._currentChapter = 5
    writingView._cursorOffset = 1700
    writingView._scenes = [
      { id: "s1", chapter_ids: ["5"], scene_chunks: [{ chapter_index: 5, start_pos: 0, end_pos: 1500 }] },
      { id: "s2", chapter_ids: [], scene_chunks: [{ chapter_index: 5, start_pos: 1500, end_pos: 3000 }] },
      { id: "s3", chapter_ids: ["5"] },
    ]

    expect(writingView._findCurrentScene()?.id).toBe("s2")
  })

  it("falls back to chapter_ids when offset does not match", () => {
    writingView._currentChapter = 5
    writingView._cursorOffset = 4000
    writingView._scenes = [
      { id: "s1", scene_chunks: [{ chapter_index: 5, start_pos: 0, end_pos: 1500 }] },
      { id: "s2", chapter_ids: ["5"] },
    ]

    expect(writingView._findCurrentScene()?.id).toBe("s2")
  })

  it("falls back to any scene_chunks for the chapter when chapter_ids does not match", () => {
    writingView._currentChapter = 5
    writingView._cursorOffset = 0
    writingView._scenes = [
      { id: "s1", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 5, start_pos: 0, end_pos: 100 }] },
    ]

    expect(writingView._findCurrentScene()?.id).toBe("s1")
  })
})

describe("_updateCurrentScene", () => {
  it("updates _currentSceneId to the matched scene id", () => {
    writingView._currentChapter = 2
    writingView._scenes = [
      { id: "s1", chapter_ids: ["1"] },
      { id: "s2", chapter_ids: ["2"] },
    ]
    writingView._updateCurrentScene()
    expect(writingView._currentSceneId).toBe("s2")
  })

  it("sets _currentSceneId to null when no scene matches", () => {
    writingView._currentChapter = 99
    writingView._scenes = [{ id: "s1", chapter_ids: ["1"] }]
    writingView._currentSceneId = "s1"
    writingView._updateCurrentScene()
    expect(writingView._currentSceneId).toBeNull()
  })
})

describe("cursor events", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    writingView._currentChapter = 1
    writingView._scenes = [{ id: "s1", chapter_ids: ["1"], title: "Scene A" }]
    writingView._currentSceneId = null
    writingView._cursorOffset = 0
    document.body.innerHTML = `
      <div id="workspace-content">
        <textarea id="writing-editor">hello world</textarea>
        <div id="writing-panel-container"></div>
      </div>
    `
    writingView._bindEvents()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("click updates _cursorOffset and re-renders the panel", () => {
    const editor = document.getElementById("writing-editor")
    editor.selectionStart = 5
    editor.click()
    expect(writingView._cursorOffset).toBe(5)
    expect(document.getElementById("writing-panel-container").innerHTML).toContain("Scene A")
  })

  it("select updates _cursorOffset and re-renders the panel", () => {
    const editor = document.getElementById("writing-editor")
    editor.selectionStart = 3
    editor.dispatchEvent(new Event("select"))
    expect(writingView._cursorOffset).toBe(3)
    expect(document.getElementById("writing-panel-container").innerHTML).toContain("Scene A")
  })

  it("keyup debounces panel update and updates _cursorOffset", () => {
    const editor = document.getElementById("writing-editor")
    editor.selectionStart = 7
    // happy-dom fires select when selectionStart changes, which updates the panel immediately
    expect(writingView._cursorOffset).toBe(7)
    expect(document.getElementById("writing-panel-container").innerHTML).toContain("Scene A")

    // Change scene data to prove the debounced keyup re-renders after the delay
    writingView._scenes = [{ id: "s2", chapter_ids: ["1"], title: "Scene B" }]
    editor.dispatchEvent(new KeyboardEvent("keyup"))
    expect(writingView._cursorDebounceTimer).not.toBeNull()
    // Scene B is not rendered yet before the debounce fires
    expect(document.getElementById("writing-panel-container").innerHTML).not.toContain("Scene B")

    vi.advanceTimersByTime(150)
    expect(writingView._cursorDebounceTimer).toBeNull()
    expect(document.getElementById("writing-panel-container").innerHTML).toContain("Scene B")
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

describe("_showSplitSceneForm", () => {
  it("无当前章节时提示", async () => {
    writingView._currentChapter = null
    await writingView._showSplitSceneForm()
    expect(toast).toHaveBeenCalledWith("请先选择章节", "warning")
  })

  it("无当前 Scene 时提示", async () => {
    writingView._currentChapter = 1
    writingView._scenes = []
    await writingView._showSplitSceneForm()
    expect(toast).toHaveBeenCalledWith("当前章节未关联 Scene", "warning")
  })

  it("展示断章弹窗并使用编辑器光标位置", async () => {
    writingView._currentChapter = 3
    writingView._scenes = [{ id: "s1", chapter_ids: ["3"], title: "Scene A" }]
    document.body.innerHTML = '<textarea id="writing-editor">abcdefghij</textarea>'
    const editor = document.getElementById("writing-editor")
    editor.selectionStart = 5

    await writingView._showSplitSceneForm()

    expect(showModal).toHaveBeenCalled()
    const [, html] = showModal.mock.calls[0]
    expect(html).toContain("split-pos")
    expect(html).toContain('value="5"')
  })

  it("无编辑器或内容过短时提示无法断章", async () => {
    writingView._currentChapter = 3
    writingView._scenes = [{ id: "s1", chapter_ids: ["3"], title: "Scene A" }]
    document.body.innerHTML = ""

    await writingView._showSplitSceneForm()

    expect(showModal).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("当前章节内容太短，无法断章", "warning")
  })

  it("编辑器内容少于 2 个字符时提示无法断章", async () => {
    writingView._currentChapter = 3
    writingView._scenes = [{ id: "s1", chapter_ids: ["3"], title: "Scene A" }]
    document.body.innerHTML = '<textarea id="writing-editor">a</textarea>'

    await writingView._showSplitSceneForm()

    expect(showModal).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("当前章节内容太短，无法断章", "warning")
  })
})

describe("_doSplitScene", () => {
  it("断章成功后切换到新章节", async () => {
    state.currentProjectId = "p1"
    writingView._currentChapter = 3
    writingView._chapterList = [3]
    writingView._scenes = [{ id: "s1", chapter_ids: ["3"], title: "Scene A" }]
    const rerenderSpy = vi.spyOn(writingView, "_rerender").mockImplementation(() => {})

    api.writing.splitChapter.mockResolvedValue({
      source_chapter_index: 3,
      new_chapter_index: 4,
      source_draft: { id: "d1", content: "abc", title: "第3章", version_number: 1 },
      new_draft: { id: "d2", content: "def", title: "第4章", version_number: 1 },
      scenes: [{ id: "s1" }, { id: "s2" }],
    })

    await writingView._doSplitScene(3, { id: "s1" })

    expect(api.writing.splitChapter).toHaveBeenCalledWith(
      3,
      { split_pos: 3, source_scene_id: "s1" },
      "p1",
    )
    expect(writingView._currentChapter).toBe(4)
    expect(writingView._currentDraftId).toBe("d2")
    expect(writingView._currentContent).toBe("def")
    expect(writingView._currentTitle).toBe("第4章")
    expect(writingView._chapterList).toEqual([3, 4])
    expect(toast).toHaveBeenCalledWith("断章完成", "success")

    rerenderSpy.mockRestore()
  })
})
