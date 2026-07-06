/**
 * writingView orchestrator 测试 — 生命周期与跨子模块协调
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import writingView from "../views/writingView.js"
import { workflowProgressStorageKey } from "../shared/workflowProgress.js"
import {
  resetState,
  clearDocument,
  autoConfirm,
  stubMethod,
  renderHtml,
  captureModalHandler,
  latestModal,
} from "./helpers.js"

beforeEach(() => {
  resetState()
  clearDocument()
  localStorage.clear()
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 })
  document.body.className = ""
  api.world.getMapSceneSummary = vi.fn()
  vi.clearAllMocks()
  confirmAction.mockReset()

  // 重置 orchestrator 共享状态
  writingView._currentChapter = null
  writingView._chapterList = []
  writingView._chapters = {}
  writingView._scenes = []
  writingView._loading = true
  writingView._chapterListLoadError = null
  writingView._focusMode = false
  writingView._forceDesktopMode = false
  writingView._bulkSelections = {}
  writingView._showBulkActions = false
  writingView._chapterTree = null
  writingView._editor = null
  writingView._versions = null
  writingView._publish = null
  writingView._deepImportRecovery = null
  writingView._autoExtraction = null
  writingView._conflictCheck = null
  writingView._scenePanel = null
  writingView._outlineFloat = null
  writingView._focusModeManager = null
  writingView._tools = null
  writingView._mobileQuickNote = null
})

afterEach(() => {
  writingView._disposeSubModules?.()
  vi.restoreAllMocks()
})

function mockChapterList() {
  api.writing.listChapters.mockResolvedValue({
    chapter_indices: [1, 3],
    chapters: [
      { chapter_index: 1, title: "第一章", word_count: 120, version_number: 1, status: "draft" },
      { chapter_index: 3, title: "第三章 归潮尽头", word_count: 1095, version_number: 1, status: "draft" },
    ],
  })
  api.outline.listScenesOrdered.mockResolvedValue([])
}

function mockEditorLoad() {
  api.writing.getVersionHistory.mockResolvedValue({
    versions: [{ id: "draft-1", version_number: 1, title: "第一章", word_count: 120 }],
  })
  api.writing.get.mockResolvedValue({
    id: "draft-1",
    title: "第一章",
    content: "第一章正文",
    version_number: 1,
    updated_at: "2026-07-05T00:00:00Z",
  })
  api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })
}

describe("writingView onEnter", () => {
  it("无项目时 loading=false", async () => {
    await writingView.onEnter()
    expect(writingView._loading).toBe(false)
  })

  it("有项目时加载章节列表和 Scene 列表", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    await writingView.onEnter()

    expect(writingView._chapterList).toEqual([1, 3])
    expect(writingView._chapters[1]).toMatchObject({ title: "第一章", wordcount: 120 })
    expect(writingView._chapters[3]).toMatchObject({ title: "第三章 归潮尽头", wordcount: 1095 })
  })

  it("章节列表 API 失败时显示错误", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockRejectedValue(new Error("fail"))
    api.outline.listScenesOrdered.mockResolvedValue([])
    await writingView.onEnter()

    expect(writingView._chapterListLoadError).toBe("fail")
    const html = await writingView.render()
    expect(html).toContain("章节列表加载失败")
  })

  it("恢复上次编辑的章节", async () => {
    state.currentProjectId = "p1"
    state.viewStates.writing = {
      projectId: "p1",
      currentChapter: 3,
      currentDraftId: "draft-3",
      currentTitle: "第三章 归潮尽头",
      currentContent: "第三章正文",
      currentVersionNumber: 1,
      currentUpdatedAt: "2026-07-05T00:03:00Z",
      isReadonly: false,
      restoreSourceVersion: null,
    }
    mockChapterList()
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "draft-3", version_number: 1, title: "第三章 归潮尽头", word_count: 1095 }],
    })
    api.writing.get.mockResolvedValue({
      id: "draft-3",
      title: "第三章 归潮尽头",
      content: "第三章正文",
      version_number: 1,
      updated_at: "2026-07-05T00:03:00Z",
    })
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })

    await writingView.onEnter()

    expect(writingView._currentChapter).toBe(3)
    expect(writingView._editor.getContent()).toBe("第三章正文")
  })

  it("切换到新项目时不恢复旧项目状态", async () => {
    state.currentProjectId = "p2"
    state.viewStates.writing = {
      projectId: "p1",
      currentChapter: 1,
      currentContent: "旧项目正文",
      currentTitle: "旧项目章节",
      currentDraftId: "old-draft",
    }
    api.writing.listChapters.mockResolvedValue({ chapter_indices: [], chapters: [] })
    api.outline.listScenesOrdered.mockResolvedValue([])

    await writingView.onEnter()

    expect(writingView._currentChapter).toBeNull()
    expect(writingView._chapterTree).toBeTruthy()
  })
})

describe("writingView render", () => {
  it("loading 状态显示加载中", async () => {
    writingView._loading = true
    const html = await writingView.render()
    expect(html).toContain("加载中")
  })

  it("无章节时显示空状态", async () => {
    writingView._loading = false
    writingView._chapterList = []
    writingView._deepImportRecovery = { renderBar: () => "" }
    const html = await writingView.render()
    expect(html).toContain("开始创作")
    expect(html).toContain('data-action="new-chapter"')
  })

  it("有章节时渲染编辑器、版本、工具栏、进度条和冲突条", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    await writingView.onEnter()
    await writingView._selectChapter(1)

    const html = await writingView.render()
    expect(html).toContain("writing-editor")
    expect(html).toContain("writing-versions-container")
    expect(html).toContain("writing-wordcount-bar")
    expect(html).toContain("writing-tools-menu")
    expect(html).toContain("writing-conflict-strip")
    expect(html).toContain('data-action="publish"')
    expect(html).toContain('data-action="autosave"')
  })

  it("AI 工具菜单显示分阶段自动提取入口", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    await writingView.onEnter()
    await writingView._selectChapter(1)

    const html = await writingView.render()
    expect(html).toContain("AI 生成草稿")
    expect(html).toContain("场景（scene）自动提取")
    expect(html).toContain("世界对象与别名/关系自动提取")
    expect(html).toContain("剧情线自动提取")
  })
})

describe("writingView chapter selection", () => {
  it("点击章节行后加载编辑器、版本并启用操作按钮", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    await writingView.onEnter()

    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()

    const row = document.querySelector('[data-action="select-chapter"][data-chapter="3"]')
    expect(row?.tagName).toBe("BUTTON")
    row.click()

    await vi.waitFor(() => {
      expect(writingView._currentChapter).toBe(3)
      expect(document.getElementById("writing-editor")).not.toBeNull()
    })
    expect(document.getElementById("writing-editor").value).toBe("第一章正文")
    expect(document.getElementById("btn-autosave").disabled).toBe(false)
    expect(document.getElementById("btn-publish").disabled).toBe(false)
  })

  it("重复点击同一章节刷新版本", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    await writingView.onEnter()
    await writingView._selectChapter(1)

    api.writing.getVersionHistory.mockClear()
    await writingView._selectChapter(1)

    expect(api.writing.getVersionHistory).toHaveBeenCalledWith(1, "p1")
  })

  it("切换章节后使用新章节 Scene 刷新冲突检查", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapter_indices: [1, 3],
      chapters: [
        { chapter_index: 1, title: "第一章", word_count: 120, version_number: 1, status: "draft" },
        { chapter_index: 3, title: "第三章", word_count: 180, version_number: 1, status: "draft" },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([
      { id: "scene-a", title: "Scene A", chapter_ids: ["1"] },
      { id: "scene-b", title: "Scene B", chapter_ids: ["3"] },
    ])
    api.writing.getVersionHistory.mockImplementation((chapterIndex) => Promise.resolve({
      versions: [{ id: `draft-${chapterIndex}`, version_number: 1 }],
    }))
    api.writing.get.mockImplementation((draftId) => Promise.resolve({
      id: draftId,
      title: draftId === "draft-3" ? "第三章" : "第一章",
      content: draftId === "draft-3" ? "第三章正文" : "第一章正文",
      version_number: 1,
      updated_at: "2026-07-05T00:00:00Z",
    }))
    api.writing.autosave.mockResolvedValue({
      version_number: 2,
      updated_at: "2026-07-05T00:01:00Z",
    })
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })

    await writingView.onEnter()
    await writingView._selectChapter(1)
    expect(state._currentSceneId).toBe("scene-a")

    api.writing.listConflictChecks.mockClear()
    await writingView._selectChapter(3)

    expect(state._currentSceneId).toBe("scene-b")
    expect(api.writing.listConflictChecks).toHaveBeenLastCalledWith({
      novel_id: "p1",
      chapter_index: 3,
      limit: 1,
    })
  })
})

describe("writingView editor callbacks", () => {
  it("字数更新同步顶部仪表盘", async () => {
    const updateDashboard = vi.fn()
    globalThis.App = { updateWordcountDashboard: updateDashboard }
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    await writingView.onEnter()
    await writingView._selectChapter(1)

    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()

    const editor = document.getElementById("writing-editor")
    editor.value = "新正文内容"
    editor.dispatchEvent(new Event("input"))

    expect(updateDashboard).toHaveBeenCalledWith(expect.objectContaining({
      chapterIndex: 1,
      chapterWords: 5,
    }))
  })

  it("保存状态变化更新徽章", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    await writingView.onEnter()
    await writingView._selectChapter(1)

    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._editor.setState({ lastPublishStatus: "未保存" })
    writingView._editor.updateMeta()

    expect(document.getElementById("writing-save-status").textContent).toBe("未保存")
  })
})

describe("writingView versions", () => {
  it("版本切换回调加载对应草稿到编辑器", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    await writingView.onEnter()
    await writingView._selectChapter(1)

    api.writing.get.mockResolvedValueOnce({
      id: "draft-old",
      title: "旧版本",
      content: "旧版本正文",
      version_number: 1,
      updated_at: "2026-07-05T00:00:00Z",
    })

    await writingView._onVersionSwitch({
      draftId: "draft-old",
      versionNumber: 1,
      isReadonly: true,
      restoreSourceVersion: 1,
      title: "旧版本",
      content: "旧版本正文",
      updatedAt: "2026-07-05T00:00:00Z",
    })

    expect(writingView._editor.isReadonly()).toBe(true)
    expect(writingView._editor.getContent()).toBe("旧版本正文")
  })
})

describe("writingView publish", () => {
  beforeEach(() => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
  })

  it("发布前调用二次确认", async () => {
    autoConfirm()
    await writingView.onEnter()
    await writingView._selectChapter(1)
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })
    api.writing.publish.mockResolvedValue({ draft: { id: "d2", version_number: 2, status: "published" } })

    await writingView._handlePublish()

    expect(confirmAction).toHaveBeenCalled()
    expect(api.writing.publish).toHaveBeenCalled()
  })

  it("高严重度未处理时阻止发布并提示", async () => {
    autoConfirm()
    await writingView.onEnter()
    await writingView._selectChapter(1)
    api.writing.listConflictChecks.mockResolvedValue({
      items: [{
        id: "c1",
        summary_json: { open_high_count: 1 },
        items: [{ severity: "high", status: "open" }],
      }],
      total: 1,
    })
    api.writing.publish.mockResolvedValue({ draft: { id: "d2", version_number: 2, status: "published" } })

    await writingView._handlePublish()

    expect(confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("未处理高严重度问题"),
      expect.any(Function),
      "继续发布",
    )
  })

  it("发布后刷新章节状态", async () => {
    autoConfirm()
    await writingView.onEnter()
    await writingView._selectChapter(1)
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })
    api.writing.publish.mockResolvedValue({
      draft: { id: "d2", version_number: 2, title: "第一章", content: "发布正文", status: "published" },
    })
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d2", version_number: 2, title: "第一章", word_count: 4, status: "published" }],
    })
    api.writing.get.mockResolvedValue({
      id: "d2",
      title: "第一章",
      content: "发布正文",
      version_number: 2,
      status: "published",
      updated_at: "2026-07-05T00:02:00Z",
    })

    await writingView._handlePublish()
    await vi.waitFor(() => expect(writingView._chapters[1].status).toBe("published"))
  })
})

describe("writingView _confirmBeforePublish", () => {
  beforeEach(() => {
    state.currentProjectId = "p1"
  })

  it("没有冲突检查记录时提示确认", async () => {
    api.writing.listConflictChecks.mockResolvedValue({ items: [] })
    autoConfirm()

    const result = await writingView._confirmBeforePublish(1, null)

    expect(result).toBe(true)
    expect(confirmAction).toHaveBeenCalledWith(
      "当前章节还没有剧情设定冲突检查记录。可以继续发布，也可以先运行检查。",
      expect.any(Function),
      "继续发布",
    )
  })

  it("存在未处理高严重度问题时提示确认", async () => {
    api.writing.listConflictChecks.mockResolvedValue({
      items: [{
        id: "c1",
        items: [{ severity: "high", status: "open" }],
        summary_json: { open_high_count: 1 },
      }],
    })
    autoConfirm()

    const result = await writingView._confirmBeforePublish(1, null)

    expect(result).toBe(true)
    expect(confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("1 个未处理高严重度问题"),
      expect.any(Function),
      "继续发布",
    )
  })

  it("没有未处理高严重度问题时直接放行", async () => {
    api.writing.listConflictChecks.mockResolvedValue({
      items: [{
        id: "c1",
        items: [{ severity: "low", status: "open" }],
        summary_json: { open_high_count: 0 },
      }],
    })

    const result = await writingView._confirmBeforePublish(1, null)

    expect(result).toBe(true)
    expect(confirmAction).not.toHaveBeenCalled()
  })
})

describe("writingView conflict check", () => {
  beforeEach(async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    await writingView.onEnter()
    await writingView._selectChapter(1)
  })

  it("运行冲突检查前先自动保存", async () => {
    api.writing.autosave.mockResolvedValue({ version_number: 2, updated_at: "2026-07-05T00:01:00Z" })
    const runSpy = vi.spyOn(writingView._conflictCheck, "run").mockResolvedValue()

    await writingView._runConflictCheck()

    expect(api.writing.autosave).toHaveBeenCalled()
    expect(runSpy).toHaveBeenCalledWith(1, expect.any(Function))
    runSpy.mockRestore()
  })

  it("定位冲突来源设置编辑器选区", () => {
    document.body.innerHTML = '<textarea id="writing-editor">主角死亡。王后沉默。</textarea>'
    const editor = document.getElementById("writing-editor")

    writingView._conflictCheck.locateItem({
      items: [{
        id: "i1",
        location_json: { text_range: { start: 0, end: 4 } },
      }],
    }, "i1")

    expect(editor.selectionStart).toBe(0)
    expect(editor.selectionEnd).toBe(4)
  })

  it("outline_scene 来源跳转到大纲视图", () => {
    writingView._conflictCheck.openSource({
      items: [{
        id: "i1",
        location_json: {
          open_target: { kind: "outline_scene", scene_id: "s1" },
          source: { label: "东门 Scene" },
        },
      }],
    }, "i1")

    expect(router.navigate).toHaveBeenCalledWith("outline", null)
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("东门 Scene"), "info")
  })
})

describe("writingView deep import / auto extraction", () => {
  beforeEach(() => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
  })

  it("自动提取任务提交后交给 deepImportRecovery 轮询", async () => {
    await writingView.onEnter()
    api.imports.startStage.mockResolvedValue({ task_id: "task-1" })
    const startTaskSpy = vi.spyOn(writingView._deepImportRecovery, "startTask").mockImplementation(() => {})

    writingView._autoExtraction.showForm("scenes")
    const handler = captureModalHandler()
    document.body.innerHTML = `
      <input id="auto-extract-start" value="1" />
      <input id="auto-extract-end" value="3" />
      <input id="auto-extract-high-quality" type="checkbox" />
    `
    await handler()

    expect(startTaskSpy).toHaveBeenCalledWith(expect.objectContaining({ taskId: "task-1" }))
    startTaskSpy.mockRestore()
  })
})

describe("writingView focus mode", () => {
  it("切换专注模式隐藏两侧面板", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    await writingView.onEnter()
    await writingView._selectChapter(1)

    document.body.innerHTML = `
      <header id="topbar"></header>
      <nav id="sidebar"></nav>
      <div id="workspace-content">${await writingView.render()}</div>
    `
    writingView._bindEvents()

    document.querySelector('[data-action="toggle-focus-mode"]').click()

    expect(writingView._focusMode).toBe(true)
    expect(document.body.classList.contains("focus-mode-active")).toBe(true)
  })
})

describe("writingView mobile quick note", () => {
  it("移动窄屏渲染快速记录模式", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 })
    await writingView.onEnter()
    await writingView._selectChapter(1)

    const html = await writingView.render()
    expect(html).toContain("mobile-quick-note")
    expect(html).toContain("mobile-note-editor")
  })
})

describe("writingView onLeave / onActivate / onDeactivate", () => {
  it("onLeave 保存编辑状态", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    await writingView.onEnter()
    await writingView._selectChapter(1)

    writingView.onLeave()

    expect(state.viewStates.writing.projectId).toBe("p1")
    expect(state.viewStates.writing.currentChapter).toBe(1)
    expect(state.viewStates.writing.currentTitle).toBe("第一章")
  })

  it("onActivate 重新绑定事件", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    await writingView.onEnter()
    await writingView._selectChapter(1)

    const bindSpy = vi.spyOn(writingView, "_bindEvents").mockImplementation(() => {})
    await writingView.onActivate()
    expect(bindSpy).toHaveBeenCalled()
    bindSpy.mockRestore()
  })
})

describe("writingView bulk actions", () => {
  it("批量删除选中章节并清空当前章状态", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapter_indices: [1, 2],
      chapters: [
        { chapter_index: 1, title: "一", word_count: 10, version_number: 1 },
        { chapter_index: 2, title: "二", word_count: 10, version_number: 1 },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([])
    mockEditorLoad()
    api.writing.deleteChapter.mockResolvedValue({})
    autoConfirm()
    await writingView.onEnter()
    await writingView._selectChapter(2)

    // 模拟 chapterTree 的批量删除回调
    writingView._chapterTree._setBulkSelections({ "writing-chapters": new Set(["1", "2"]) })
    writingView._chapterTree.runBulkAction("delete-chapters")

    await vi.waitFor(() => {
      expect(api.writing.deleteChapter).toHaveBeenCalledWith(1, "p1")
      expect(api.writing.deleteChapter).toHaveBeenCalledWith(2, "p1")
    })
    await vi.waitFor(() => expect(writingView._currentChapter).toBeNull())
  })
})

describe("writingView XSS safety", () => {
  it("版本下拉转义 draft id 属性", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: 'd1" onclick="alert(1)', version_number: 1, title: "第一章", word_count: 1 }],
    })
    api.writing.get.mockResolvedValue({
      id: 'd1" onclick="alert(1)',
      title: "第一章",
      content: "正文",
      version_number: 1,
    })
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })
    await writingView.onEnter()
    await writingView._selectChapter(1)

    const container = renderHtml(writingView._versions.render())
    const option = container.querySelector("option")

    expect(option?.getAttribute("onclick")).toBeNull()
    expect(option?.value).toBe('d1" onclick="alert(1)')
  })
})

describe("writingView new chapter", () => {
  beforeEach(async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapter_indices: [1, 2],
      chapters: [
        { chapter_index: 1, title: "第一章", word_count: 4, version_number: 1, status: "draft" },
        { chapter_index: 2, title: "第二章", word_count: 6, version_number: 1, status: "draft" },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([])
    api.writing.autosave.mockResolvedValue({
      version_number: 2,
      updated_at: "2026-07-05T00:01:00Z",
    })
    api.writing.getVersionHistory.mockImplementation((chapterIndex) => Promise.resolve({
      versions: [{ id: `draft-${chapterIndex}`, version_number: 1, title: `第 ${chapterIndex} 章`, word_count: 0 }],
    }))
    api.writing.get.mockImplementation((draftId) => Promise.resolve({
      id: draftId,
      title: `第 ${draftId.replace("draft-", "")} 章`,
      content: "",
      version_number: 1,
      updated_at: "2026-07-05T00:00:00Z",
    }))
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })
  })

  it("创建新章节后出现在章节树并自动选中", async () => {
    api.writing.autosaveDraftOnly.mockResolvedValue({
      id: "draft-3",
      chapter_index: 3,
      title: "第 3 章",
      content: "",
      version_number: 1,
      status: "draft",
      updated_at: "2026-07-05T00:00:00Z",
    })
    await writingView.onEnter()

    await writingView._chapterTree.newChapter()
    await vi.waitFor(() => {
      expect(writingView._currentChapter).toBe(3)
    })

    expect(writingView._chapterList).toContain(3)
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    expect(document.getElementById("writing-editor")).not.toBeNull()
    expect(document.querySelector('[data-chapter="3"]')).not.toBeNull()
  })

  it("章节树中点击新建章节创建下一章并选中", async () => {
    api.writing.autosaveDraftOnly.mockImplementation((payload) => Promise.resolve({
      id: `draft-${payload.chapter_index}`,
      chapter_index: payload.chapter_index,
      title: payload.title,
      content: payload.content,
      version_number: 1,
      status: "draft",
      updated_at: `2026-07-05T00:0${payload.chapter_index}:00Z`,
    }))
    await writingView.onEnter()
    await writingView._selectChapter(2)

    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()

    document.querySelector('.chapter-tree-actions [data-action="new-chapter"]').click()
    await vi.waitFor(() => {
      expect(writingView._currentChapter).toBe(3)
    })

    expect(writingView._chapterList).toEqual([1, 2, 3])
    expect(document.getElementById("writing-title-input").value).toBe("第 3 章")
    expect(document.getElementById("writing-editor").value).toBe("")
    expect(document.querySelector('[data-chapter="3"]').className).toContain("chapter-row--active")
  })

  it("新建章节不继承上一章正文", async () => {
    api.writing.get.mockImplementation((draftId) => Promise.resolve({
      id: draftId,
      title: `第 ${draftId.replace("draft-", "")} 章`,
      content: draftId === "draft-2" ? "上一章正文不应继承" : "",
      version_number: 1,
      updated_at: "2026-07-05T00:00:00Z",
    }))
    api.writing.autosaveDraftOnly.mockImplementation((payload) => Promise.resolve({
      id: `draft-${payload.chapter_index}`,
      chapter_index: payload.chapter_index,
      title: payload.title,
      content: "",
      version_number: 1,
      status: "draft",
      updated_at: `2026-07-05T00:0${payload.chapter_index}:00Z`,
    }))
    await writingView.onEnter()
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()
    await writingView._selectChapter(2)
    expect(document.getElementById("writing-editor").value).toBe("上一章正文不应继承")

    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()
    document.querySelector('.chapter-tree-actions [data-action="new-chapter"]').click()
    await vi.waitFor(() => {
      expect(writingView._currentChapter).toBe(3)
    })

    expect(document.getElementById("writing-editor").value).toBe("")
    expect(document.getElementById("writing-title-input").value).toBe("第 3 章")
  })
})

describe("writingView chapter switching", () => {
  beforeEach(async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapter_indices: [1, 2],
      chapters: [
        { chapter_index: 1, title: "第一章", word_count: 5, version_number: 1, status: "draft" },
        { chapter_index: 2, title: "第二章", word_count: 7, version_number: 1, status: "draft" },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([])
    api.writing.autosave.mockResolvedValue({
      version_number: 2,
      updated_at: "2026-07-05T00:01:00Z",
    })
    api.writing.getVersionHistory.mockImplementation((chapterIndex) => Promise.resolve({
      versions: [{ id: `draft-${chapterIndex}`, version_number: 1, title: `第 ${chapterIndex} 章`, word_count: chapterIndex === 1 ? 5 : 7 }],
    }))
    api.writing.get.mockImplementation((draftId) => Promise.resolve({
      id: draftId,
      title: `第 ${draftId.replace("draft-", "")} 章`,
      content: draftId === "draft-1" ? "第一章正文" : "第二章正文",
      version_number: 1,
      updated_at: "2026-07-05T00:00:00Z",
    }))
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })
    await writingView.onEnter()
  })

  it("切换章节加载对应章节内容", async () => {
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()
    await writingView._selectChapter(1)
    expect(document.getElementById("writing-editor").value).toBe("第一章正文")

    await writingView._selectChapter(2)
    expect(document.getElementById("writing-editor").value).toBe("第二章正文")
  })

  it("切换回之前章节恢复之前内容", async () => {
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()
    await writingView._selectChapter(1)
    await writingView._selectChapter(2)
    await writingView._selectChapter(1)
    expect(document.getElementById("writing-editor").value).toBe("第一章正文")
  })
})

describe("writingView version history", () => {
  beforeEach(async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [
        { id: "draft-2", version_number: 2, title: "第一章", word_count: 5 },
        { id: "draft-1", version_number: 1, title: "第一章", word_count: 4 },
      ],
    })
    api.writing.get.mockImplementation((draftId) => Promise.resolve({
      id: draftId,
      title: "第一章",
      content: draftId === "draft-1" ? "旧版本正文" : "新版本正文",
      version_number: draftId === "draft-1" ? 1 : 2,
      updated_at: "2026-07-05T00:00:00Z",
    }))
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })
    await writingView.onEnter()
    await writingView._selectChapter(1)
  })

  it("点击历史按钮打开版本历史弹窗", async () => {
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()
    document.querySelector('[data-action="version-history"]').click()
    await vi.waitFor(() => {
      expect(showModal).toHaveBeenCalled()
    })
    const modal = latestModal()
    expect(modal.title).toContain("版本历史")
    expect(modal.body.html).toContain("draft-1")
    expect(modal.body.html).toContain("draft-2")
  })

  it("预览旧版本切换到只读模式", async () => {
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()
    document.querySelector('[data-action="version-history"]').click()
    await vi.waitFor(() => expect(showModal).toHaveBeenCalled())

    const { body } = latestModal()
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>${body.html}`
    writingView._bindEvents()
    writingView._versions.bindVersionHistoryEvents()

    document.querySelector('.version-preview-btn[data-version="1"]').click()
    await vi.waitFor(() => {
      expect(document.getElementById("writing-editor").readOnly).toBe(true)
    })
    expect(document.getElementById("writing-editor").value).toBe("旧版本正文")
  })

  it("恢复旧版本创建可编辑新版本", async () => {
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()
    document.querySelector('[data-action="version-history"]').click()
    await vi.waitFor(() => expect(showModal).toHaveBeenCalled())

    const { body } = latestModal()
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>${body.html}`
    writingView._bindEvents()
    writingView._versions.bindVersionHistoryEvents()
    autoConfirm()

    document.querySelector('.version-restore-btn[data-version="1"]').click()
    await vi.waitFor(() => {
      expect(document.getElementById("writing-editor").value).toBe("旧版本正文")
    })
    expect(document.getElementById("writing-editor").readOnly).toBe(false)
    expect(document.getElementById("btn-autosave").textContent).toBe("发布为新版本")
  })
})

describe("writingView publish flow", () => {
  beforeEach(async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    api.writing.autosave.mockResolvedValue({
      version_number: 2,
      updated_at: "2026-07-05T00:01:00Z",
    })
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })
    await writingView.onEnter()
    await writingView._selectChapter(1)
  })

  it("未选择章节时发布按钮禁用，选择后启用", async () => {
    await writingView._selectChapter(null)
    writingView._editor.setState({ chapter: null, content: "", title: "" })
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    expect(document.getElementById("btn-publish").disabled).toBe(true)

    await writingView._selectChapter(1)
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    expect(document.getElementById("btn-publish").disabled).toBe(false)
  })

  it("发布成功后显示成功状态并刷新章节树", async () => {
    api.writing.publish.mockResolvedValue({
      draft: { id: "d2", version_number: 2, status: "published" },
    })
    api.writing.listChapters.mockResolvedValue({
      chapter_indices: [1],
      chapters: [{ chapter_index: 1, title: "第一章", word_count: 4, version_number: 2, status: "published" }],
    })
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d2", version_number: 2, title: "第一章", word_count: 4, status: "published" }],
    })
    api.writing.get.mockResolvedValue({
      id: "d2",
      title: "第一章",
      content: "发布正文",
      version_number: 2,
      status: "published",
      updated_at: "2026-07-05T00:02:00Z",
    })
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()
    autoConfirm()
    await writingView._handlePublish()

    expect(api.writing.publish).toHaveBeenCalledWith({
      novel_id: "p1",
      chapter_index: 1,
      scene_id: null,
      title: "第一章",
      content: "第一章正文",
    })
    await vi.waitFor(() => {
      const status = document.querySelector('[data-chapter="1"] .chapter-status')
      expect(status?.className).toContain("chapter-status--published")
    })
    expect(toast).toHaveBeenCalledWith("已发布", "success")
  })

  it("发布返回任务ID时显示轮询进度条", async () => {
    vi.useFakeTimers()
    api.writing.publish.mockResolvedValue({
      draft: { id: "d2", version_number: 2, status: "published" },
      task_id: "publish-task-1",
    })
    api.tasks.get.mockResolvedValue({
      task_id: "publish-task-1",
      task_type: "publish_chapter",
      status: "done",
      progress: 1,
      result: { message: "发布完成" },
    })
    document.body.innerHTML = `
      <div id="workspace-content">${await writingView.render()}</div>
      <span id="publish-status-dot"></span>
    `
    writingView._bindEvents()
    autoConfirm()
    await writingView._handlePublish()

    expect(api.writing.publish).toHaveBeenCalled()
    expect(writingView._publish.renderBar()).toContain("发布正文")

    await vi.advanceTimersByTimeAsync(2500)
    await vi.waitFor(() => {
      expect(document.getElementById("writing-publish-bar-container").textContent).toContain("发布完成")
    })
    vi.useRealTimers()
  })
})

describe("writingView conflict check strip", () => {
  it("存在检查记录时渲染冲突条", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    api.writing.listConflictChecks.mockResolvedValue({
      items: [{
        id: "c1",
        chapter_index: 1,
        summary_json: { total: 3 },
        items: [],
        created_at: "2026-07-05T10:00:00Z",
      }],
      total: 1,
    })
    await writingView.onEnter()
    await writingView._selectChapter(1)

    const html = await writingView.render()
    expect(html).toContain("writing-conflict-strip")
    expect(html).toContain("发现 3 个冲突")
    expect(html).toContain('data-action="open-conflict-check"')
  })

  it("点击冲突条打开检查详情弹窗", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    const check = {
      id: "c1",
      chapter_index: 1,
      summary_json: { total: 1 },
      items: [{ id: "i1", severity: "high", status: "open", kind: "motivation_gap", source_module: "ai", evidence_summary: "缺少动机" }],
      created_at: "2026-07-05T10:00:00Z",
    }
    api.writing.listConflictChecks.mockResolvedValue({ items: [check], total: 1 })
    await writingView.onEnter()
    await writingView._selectChapter(1)

    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()

    document.querySelector('[data-action="open-conflict-check"]').click()
    await vi.waitFor(() => {
      expect(showModal).toHaveBeenCalled()
    })
    const modal = latestModal()
    expect(modal.title).toContain("剧情设定冲突检查")
    expect(modal.body.html).toContain("缺少动机")
  })
})

describe("writingView scene panel cursor tracking", () => {
  beforeEach(async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapter_indices: [1],
      chapters: [{ chapter_index: 1, title: "第一章", word_count: 20, version_number: 1, status: "draft" }],
    })
    api.outline.listScenesOrdered.mockResolvedValue([
      { id: "s1", title: "Scene A", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 10 }] },
      { id: "s2", title: "Scene B", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 1, start_pos: 10, end_pos: 20 }] },
    ])
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "draft-1", version_number: 1, title: "第一章", word_count: 20 }],
    })
    api.writing.get.mockResolvedValue({
      id: "draft-1",
      title: "第一章",
      content: "0123456789abcdefghij",
      version_number: 1,
      updated_at: "2026-07-05T00:00:00Z",
    })
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })
    await writingView.onEnter()
    await writingView._selectChapter(1)
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()
  })

  it("点击编辑器更新右侧面板当前Scene", async () => {
    const editor = document.getElementById("writing-editor")
    editor.selectionStart = editor.selectionEnd = 15
    editor.focus()
    editor.click()

    await vi.waitFor(() => {
      expect(document.getElementById("writing-panel-container").textContent).toContain("Scene B")
    })
  })

  it("键盘输入后光标位置更新Scene", async () => {
    vi.useFakeTimers()
    const editor = document.getElementById("writing-editor")
    editor.selectionStart = editor.selectionEnd = 5
    editor.focus()
    editor.dispatchEvent(new KeyboardEvent("keyup"))
    vi.advanceTimersByTime(200)

    await vi.waitFor(() => {
      expect(document.getElementById("writing-panel-container").textContent).toContain("Scene A")
    })
    vi.useRealTimers()
  })
})

describe("writingView offline recovery", () => {
  it("版本接口失败时从localStorage恢复本地暂存", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    api.writing.getVersionHistory.mockRejectedValue(new Error("backend failed"))
    localStorage.setItem("draft_backup_p1_1", JSON.stringify({
      content: "本地暂存正文",
      title: "本地暂存标题",
      chapter_index: 1,
      timestamp: Date.now(),
    }))
    autoConfirm()
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })

    await writingView.onEnter()
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    await writingView._selectChapter(1)

    expect(confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("检测到本地暂存的第 1 章内容"),
      expect.any(Function),
      "恢复本地内容",
    )
    expect(document.getElementById("writing-editor").value).toBe("本地暂存正文")
    expect(document.getElementById("writing-title-input").value).toBe("本地暂存标题")
  })
})

describe("writingView AI extract chapter cards", () => {
  beforeEach(async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    mockEditorLoad()
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })
    await writingView.onEnter()
    await writingView._selectChapter(1)
  })

  it("AI工具菜单包含提取章节卡按钮", async () => {
    const html = await writingView.render()
    expect(html).toContain('data-action="extract-cards"')
    expect(html).toContain("AI 提取章节卡")
  })

  it("点击提取章节卡打开弹窗", async () => {
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`
    writingView._bindEvents()
    document.querySelector('[data-action="extract-cards"]').click()
    await vi.waitFor(() => {
      expect(showModal).toHaveBeenCalled()
    })
    const modal = latestModal()
    expect(modal.title).toContain("AI 提取章节卡")
  })
})

describe("writingView scene map summary", () => {
  it("scene面板显示地图摘要", async () => {
    state.currentProjectId = "p1"
    mockChapterList()
    api.outline.listScenesOrdered.mockResolvedValue([
      { id: "s1", title: "东门", chapter_ids: ["1"] },
    ])
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "draft-1", version_number: 1, title: "第一章", word_count: 10 }],
    })
    api.writing.get.mockResolvedValue({
      id: "draft-1",
      title: "第一章",
      content: "正文",
      version_number: 1,
      updated_at: "2026-07-05T00:00:00Z",
    })
    api.world.getMapSceneSummary.mockResolvedValue({
      primary_location: { name: "洛阳外城" },
      characters: [{ name: "沈砚" }],
      events: [{ name: "东门封锁" }],
    })
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })

    await writingView.onEnter()
    await writingView._selectChapter(1)
    document.body.innerHTML = `<div id="workspace-content">${await writingView.render()}</div>`

    await vi.waitFor(() => {
      expect(document.getElementById("writing-panel-container").textContent).toContain("洛阳外城")
    })
    expect(document.getElementById("writing-panel-container").textContent).toContain("沈砚")
    expect(document.getElementById("writing-panel-container").textContent).toContain("东门封锁")
  })
})
