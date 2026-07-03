/**
 * writingView 测试 — 核心生命周期和行为
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import writingView from "../views/writingView.js"
import { workflowProgressStorageKey } from "../shared/workflowProgress.js"
import { resetState, clearDocument, autoConfirm, stubMethod } from "./helpers.js"

beforeEach(() => {
  resetState()
  clearDocument()
  localStorage.clear()
  writingView._chapters = {}
  writingView._chapterList = []
  writingView._chapterListLoadError = null
  writingView._currentChapter = null
  writingView._currentDraftId = null
  writingView._currentContent = null
  writingView._currentTitle = null
  writingView._currentVersionNumber = null
  writingView._versions = []
  writingView._scenes = []
  writingView._currentSceneId = null
  writingView._cursorOffset = 0
  writingView._sceneMapSummary = null
  writingView._sceneMapSummaryError = null
  writingView._sceneMapSummarySceneId = null
  writingView._sceneMapSummaryLoading = false
  writingView._publishTaskId = null
  writingView._publishProgress = null
  writingView._deepImportTaskId = null
  writingView._deepImportProgress = null
  writingView._focusMode = false
  writingView._forceDesktopMode = false
  document.body.className = ""
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 })
  api.world.getMapSceneSummary = vi.fn()
  vi.clearAllMocks()
  confirmAction.mockReset()
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
    expect(html).toContain("章节（1）")
    expect(html).toContain("writing-editor")
  })

  it("AI 工具菜单显示三个分阶段自动提取入口并移除深度导入入口", () => {
    state.currentProjectId = "p1"
    writingView._currentChapter = 1
    writingView._isReadonly = false

    const html = writingView._renderEditorToolsMenu(true)

    expect(html).toContain("生成")
    expect(html).toContain("提取")
    expect(html).toContain("检查")
    expect(html).toContain("地图")
    expect(html).toContain("场景（scene）自动提取")
    expect(html).toContain("世界对象与别名/关系自动提取")
    expect(html).toContain("剧情线自动提取")
    expect(html).not.toContain('data-action="deep-import"')
  })

  it("编辑器显示保存状态徽章", () => {
    writingView._currentChapter = 1
    writingView._currentDraftId = "d1"
    writingView._currentVersionNumber = 2
    writingView._currentTitle = "第一章"
    writingView._currentContent = "正文"
    writingView._isReadonly = false

    const html = writingView._renderEditor()

    expect(html).toContain("writing-save-badge")
    expect(html).toContain("writing-version-badge")
  })

  it("编辑器使用写作字体、字数条和专注模式入口", () => {
    writingView._currentChapter = 1
    writingView._currentDraftId = "d1"
    writingView._currentContent = "第一段\n\n第二段"
    writingView._currentTitle = "第一章"
    writingView._isReadonly = false

    const html = writingView._renderEditor()

    expect(html).toContain("novel-editor")
    expect(html).toContain("writing-wordcount-bar")
    expect(html).toContain('data-action="toggle-focus-mode"')
    expect(html).toContain("专注模式")
  })

  it("章节树主视图显示简化行、状态点和上下章按钮", () => {
    writingView._chapterList = [1, 2]
    writingView._chapters = {
      1: { title: "开篇", draftCount: 1, wordcount: 1200 },
      2: { title: "转折", draftCount: 0 },
    }
    writingView._currentChapter = 1
    writingView._scenes = []

    const html = writingView._renderSceneTree()

    expect(html).toContain('data-action="prev-chapter"')
    expect(html).toContain('data-action="next-chapter"')
    expect(html).toContain("chapter-row")
    expect(html).toContain("1,200 字")
    expect(html).not.toContain("批量删除章节")
  })

  it("更新字数统计会同步底部和顶部仪表盘", () => {
    const updateDashboard = vi.fn()
    globalThis.App = { updateWordcountDashboard: updateDashboard }
    state.currentProjectId = "p1"
    writingView._currentChapter = 1
    document.body.innerHTML = `
      <textarea id="writing-editor">一二三\n\n四五</textarea>
      <span id="wc-chapter"></span>
      <span id="wc-paragraphs"></span>
      <span id="wc-readtime"></span>
      <span id="wc-daily"></span>
      <div id="wc-goal-fill"></div>
    `

    writingView._updateWordcount()

    expect(document.getElementById("wc-chapter").textContent).toBe("7")
    expect(document.getElementById("wc-paragraphs").textContent).toBe("2")
    expect(updateDashboard).toHaveBeenCalledWith(expect.objectContaining({
      chapterIndex: 1,
      chapterWords: 7,
      todayWords: 7,
    }))
  })

  it("专注模式切换隐藏两侧面板并保留编辑器聚焦", () => {
    writingView._focusMode = false
    document.body.innerHTML = `
      <header id="topbar"></header>
      <nav id="sidebar"></nav>
      <div id="writing-tree-container"></div>
      <textarea id="writing-editor"></textarea>
      <div id="writing-panel-container"></div>
    `

    writingView._toggleFocusMode()

    expect(writingView._focusMode).toBe(true)
    expect(document.body.classList.contains("focus-mode-active")).toBe(true)
    expect(document.getElementById("writing-tree-container").classList.contains("focus-hidden")).toBe(true)
  })

  it("移动窄屏渲染快速记录模式", async () => {
    writingView._loading = false
    writingView._chapterList = [1]
    writingView._currentChapter = 1
    writingView._currentContent = "灵感"
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 })

    const html = await writingView.render()

    expect(html).toContain("mobile-quick-note")
    expect(html).toContain("mobile-note-editor")
  })

  it("移动快速记录在无草稿时使用现有草稿创建接口", async () => {
    state.currentProjectId = "p1"
    writingView._currentChapter = 3
    writingView._currentDraftId = null
    writingView._currentTitle = null
    api.writing.autosaveDraftOnly.mockResolvedValue({
      id: "d3",
      version_number: 1,
      updated_at: "2026-07-03T00:00:00Z",
    })
    document.body.innerHTML = '<textarea id="mobile-note-editor">新灵感</textarea>'

    await writingView._saveMobileNote()

    expect(api.writing.autosaveDraftOnly).toHaveBeenCalledWith({
      novel_id: "p1",
      chapter_index: 3,
      title: "第 3 章",
      content: "新灵感",
    })
    expect(api.writing.autosave).not.toHaveBeenCalled()
    expect(writingView._currentDraftId).toBe("d3")
    expect(toast).toHaveBeenCalledWith("已保存到草稿", "success")
  })

  it("移动快速记录保存失败时只保留本地暂存并提示失败", async () => {
    state.currentProjectId = "p1"
    writingView._currentChapter = 4
    writingView._currentDraftId = null
    api.writing.autosaveDraftOnly.mockRejectedValue(new Error("接口失败"))
    document.body.innerHTML = '<textarea id="mobile-note-editor">离线灵感</textarea>'

    await writingView._saveMobileNote()

    expect(toast).toHaveBeenCalledWith("接口失败", "error")
    expect(toast).not.toHaveBeenCalledWith("已保存到草稿", "success")
    expect(JSON.parse(localStorage.getItem("draft_backup_p1_4"))).toEqual(expect.objectContaining({
      content: "离线灵感",
      title: "第 4 章",
    }))
  })

  it("写作台读取项目级作者偏好并兼容旧偏好", () => {
    state.currentProjectId = "p1"
    localStorage.setItem("novel_author_preferences:p1", JSON.stringify({
      dailyGoal: 6500,
      defaultFocusMode: true,
    }))

    expect(writingView._getDailyGoal()).toBe(6500)
    expect(writingView._getFocusDefault()).toBe(true)

    localStorage.removeItem("novel_author_preferences:p1")
    localStorage.setItem("novel_daily_goal", "3200")
    localStorage.setItem("novel_focus_default", "1")

    expect(writingView._getDailyGoal()).toBe(3200)
    expect(writingView._getFocusDefault()).toBe(true)
  })

  it("版本接口失败时仍提示恢复本地暂存", async () => {
    state.currentProjectId = "p1"
    autoConfirm()
    api.writing.getVersionHistory.mockRejectedValue(new Error("backend failed"))
    localStorage.setItem("draft_backup_p1_1", JSON.stringify({
      content: "本地暂存正文",
      title: "本地暂存标题",
      chapter_index: 1,
      timestamp: Date.now(),
    }))

    await writingView._refreshVersions(1)

    expect(writingView._versions).toEqual([])
    expect(confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("检测到本地暂存的第 1 章内容"),
      expect.any(Function),
      "恢复本地内容",
    )
    expect(writingView._currentContent).toBe("本地暂存正文")
    expect(writingView._currentTitle).toBe("本地暂存标题")
  })

  it("编辑器工具栏显示打开地图按钮", async () => {
    state.currentProjectId = "p1"
    writingView._loading = false
    writingView._chapterList = [1]
    writingView._currentChapter = 1
    writingView._chapters = { 1: { draftCount: 0 } }

    const html = await writingView.render()

    expect(html).toContain('data-action="open-map"')
    expect(html).toContain("打开地图")
  })

  it("编辑器工具栏显示 AI 生成草稿按钮", async () => {
    state.currentProjectId = "p1"
    writingView._loading = false
    writingView._chapterList = [1]
    writingView._currentChapter = 1
    writingView._chapters = { 1: { draftCount: 0 } }

    const html = await writingView.render()

    expect(html).toContain('data-action="ai-generate-draft"')
    expect(html).toContain("AI 生成草稿")
  })
})

describe("writingView AI generation", () => {
  it("确认 AI 参考资料后提交正文生成任务", async () => {
    state.currentProjectId = "p1"
    writingView._currentChapter = 2
    writingView._currentTitle = "夜访王都"
    document.body.innerHTML = `
      <div id="modal-overlay" class="hidden">
        <div id="modal-title"></div>
        <div id="modal-body"></div>
        <div id="modal-footer"></div>
      </div>
    `
    api.context.confirm.mockResolvedValue({
      id: "confirm-1",
      user_note: "保持克制",
      selected_asset_ids: {},
      warnings: [],
    })
    api.writing.generate.mockResolvedValue({ task_id: "task-1", status: "pending" })

    const promise = writingView._generateDraft()
    await Promise.resolve()
    document.querySelectorAll("#modal-footer button")[1].click()
    await promise

    expect(api.writing.generate).toHaveBeenCalledWith({
      novel_id: "p1",
      chapter_index: 2,
      title: "夜访王都",
      instruction: "保持克制",
      context_confirmation_id: "confirm-1",
    })
  })
})

describe("writingView onEnter", () => {
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

  it("API 失败时显示章节列表加载失败提示", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockRejectedValue(new Error("fail"))
    await writingView.onEnter()
    const html = await writingView.render()

    expect(writingView._chapterList).toEqual([])
    expect(html).toContain("章节列表加载失败")
    expect(html).toContain("可稍后重试")
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

describe("writingView map integration", () => {
  it("opens current Scene map target in a new browser tab", () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null)
    state.currentProjectId = "p1"
    writingView._sceneMapSummary = {
      open_target: { mode: "map", map_id: "m1", scene_id: "s1" },
    }

    writingView._openMapForCurrentScene()

    expect(openSpy).toHaveBeenCalledWith(
      "#workbench/p1/map?map_id=m1&scene_id=s1&mode=map",
      "_blank",
      "noopener"
    )
    openSpy.mockRestore()
  })

  it("opens fallback map target in a new tab and shows fallback message", () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null)
    state.currentProjectId = "p1"
    writingView._scenes = [{ id: "s1", chapter_ids: ["1"] }]
    writingView._currentChapter = 1
    writingView._sceneMapSummary = {
      open_target: {
        mode: "recent",
        scene_id: "s1",
        fallback_message: "当前 Scene 暂无地图上下文，已回退到最近地图",
      },
    }

    writingView._openMapForCurrentScene()

    expect(toast).toHaveBeenCalledWith(
      "当前 Scene 暂无地图上下文，已回退到最近地图",
      "warning",
    )
    expect(openSpy).toHaveBeenCalledWith(
      "#workbench/p1/map?scene_id=s1&mode=recent",
      "_blank",
      "noopener"
    )
    openSpy.mockRestore()
  })

  it("renders compact Scene map summary", () => {
    state.currentProjectId = "p1"
    writingView._currentChapter = 1
    writingView._scenes = [{ id: "s1", scene_index: 1, title: "东门", chapter_ids: ["1"] }]
    writingView._sceneMapSummary = {
      primary_location: { name: "洛阳外城" },
      characters: [{ name: "沈砚" }],
      events: [{ name: "东门封锁" }],
      factions: [{ name: "北府" }],
      crises: [{ name: "粮仓起火" }],
      risks: [{ message: "陆青跨图移动需复核" }],
      warnings: [{ message: "陆青上一场在江陵，需确认移动合理性" }],
    }

    const html = writingView._renderScenePanel()

    expect(html).toContain("地图摘要")
    expect(html).toContain("洛阳外城")
    expect(html).toContain("沈砚")
    expect(html).toContain("东门封锁")
    expect(html).toContain("北府")
    expect(html).toContain("粮仓起火")
    expect(html).toContain("陆青跨图移动需复核")
    expect(html).toContain("陆青上一场")
  })

  it("renders stable copy for spatial continuity warning codes", () => {
    state.currentProjectId = "p1"
    writingView._currentChapter = 1
    writingView._scenes = [{ id: "s1", chapter_ids: ["1"], title: "旧城门" }]
    writingView._sceneMapSummary = {
      primary_location: null,
      characters: [],
      events: [],
      factions: [],
      warnings: [
        { code: "scene_without_map_context" },
        { code: "scene_without_location" },
        { code: "character_cross_map", message: "陆青上一场在其他地图，需确认移动合理性" },
      ],
    }

    const html = writingView._renderScenePanel()

    expect(html).toContain("当前 Scene 暂无地图上下文")
    expect(html).toContain("当前 Scene 暂无主地点")
    expect(html).toContain("陆青上一场在其他地图")
  })

  it("shows summary fallback text when scene-summary fails", async () => {
    state.currentProjectId = "p1"
    api.world.getMapSceneSummary.mockRejectedValue(new Error("fail"))

    await writingView._loadCurrentSceneMapSummary({ id: "s1" })

    expect(writingView._sceneMapSummary).toBeNull()
    expect(writingView._sceneMapSummaryError).toBe("地图摘要暂不可用")
  })

  it("does not cache stale scene-summary results after scene switch", async () => {
    state.currentProjectId = "p1"
    writingView._currentSceneId = "s1"
    let resolveSummary
    api.world.getMapSceneSummary.mockReturnValue(new Promise((resolve) => {
      resolveSummary = resolve
    }))

    const pending = writingView._loadCurrentSceneMapSummary({ id: "s1" })
    writingView._currentSceneId = "s2"
    resolveSummary({ primary_location: { name: "旧地点" } })
    await pending

    expect(writingView._sceneMapSummary).toBeNull()
    expect(writingView._sceneMapSummaryError).toBeNull()
    expect(writingView._sceneMapSummaryLoading).toBe(false)
  })
})

describe("writingView conflict checks", () => {
  beforeEach(() => {
    state.currentProjectId = "p1"
    writingView._currentChapter = 1
    writingView._currentDraftId = "d1"
    writingView._currentVersionNumber = 2
    writingView._currentUpdatedAt = "2026-06-29T00:00:00Z"
    writingView._currentTitle = "第一章"
    writingView._currentContent = "旧正文"
    writingView._scenes = [{ id: "s1", title: "东门", chapter_ids: ["1"] }]
    writingView._currentSceneId = "s1"
    document.body.innerHTML = `
      <input id="writing-title-input" value="第一章" />
      <textarea id="writing-editor">新正文</textarea>
    `
  })

  it("does not autosave or create a conflict check when options modal is cancelled", async () => {
    const pending = writingView._runConflictCheck()
    await Promise.resolve()
    showModal.mock.calls[0][2][0].handler()
    await pending

    expect(api.writing.autosave).not.toHaveBeenCalled()
    expect(api.writing.autosaveDraftOnly).not.toHaveBeenCalled()
    expect(api.writing.createConflictCheck).not.toHaveBeenCalled()
    expect(api.writing.listConflictChecks).not.toHaveBeenCalled()
  })

  it("treats global modal close as conflict check cancellation", async () => {
    document.body.insertAdjacentHTML("beforeend", `
      <button id="modal-close">x</button>
      <div id="modal-overlay"></div>
    `)

    const pending = writingView._runConflictCheck()
    await Promise.resolve()
    document.getElementById("modal-close").click()
    await pending

    expect(api.writing.autosave).not.toHaveBeenCalled()
    expect(api.writing.autosaveDraftOnly).not.toHaveBeenCalled()
    expect(api.writing.createConflictCheck).not.toHaveBeenCalled()
    expect(api.writing.listConflictChecks).not.toHaveBeenCalled()
  })

  it("ignores repeated conflict check triggers while options modal is active", async () => {
    const first = writingView._runConflictCheck()
    const second = writingView._runConflictCheck()
    await Promise.resolve()

    expect(showModal).toHaveBeenCalledTimes(1)

    showModal.mock.calls[0][2][0].handler()
    await first
    await second

    expect(api.writing.autosave).not.toHaveBeenCalled()
    expect(api.writing.autosaveDraftOnly).not.toHaveBeenCalled()
    expect(api.writing.createConflictCheck).not.toHaveBeenCalled()
    expect(api.writing.listConflictChecks).not.toHaveBeenCalled()
  })

  it("autosaves before creating a conflict check", async () => {
    api.writing.autosave.mockResolvedValue({
      id: "d1",
      version_number: 2,
      updated_at: "2026-06-29T00:00:01Z",
    })
    api.writing.createConflictCheck.mockResolvedValue({
      id: "c1",
      items: [],
      summary_json: { total: 0 },
    })
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })

    const pending = writingView._runConflictCheck()
    await Promise.resolve()
    expect(showModal).toHaveBeenCalledWith(
      "剧情设定冲突检查",
      expect.stringContaining("writing-conflict-include-candidates"),
      expect.any(Array),
    )
    showModal.mock.calls[0][2][1].handler()
    await pending

    expect(api.writing.autosave.mock.invocationCallOrder[0]).toBeLessThan(
      api.writing.createConflictCheck.mock.invocationCallOrder[0],
    )
    expect(api.writing.createConflictCheck).toHaveBeenCalledWith({
      novel_id: "p1",
      chapter_index: 1,
      scene_id: "s1",
      draft_id: "d1",
      version_number: 2,
      content: "新正文",
      include_candidates: false,
    })
  })

  it("passes include_candidates true when conflict check options include candidates", async () => {
    api.writing.autosave.mockResolvedValue({
      id: "d1",
      version_number: 2,
      updated_at: "2026-06-29T00:00:01Z",
    })
    api.writing.createConflictCheck.mockResolvedValue({
      id: "c1",
      items: [],
      summary_json: { total: 0 },
    })
    api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })

    const pending = writingView._runConflictCheck()
    await Promise.resolve()
    document.body.insertAdjacentHTML("beforeend", showModal.mock.calls[0][1])
    document.getElementById("writing-conflict-include-candidates").checked = true
    showModal.mock.calls[0][2][1].handler()
    await pending

    expect(api.writing.createConflictCheck).toHaveBeenCalledWith(expect.objectContaining({
      include_candidates: true,
    }))
  })

  it("does not create a conflict check when autosave fails", async () => {
    api.writing.autosave.mockRejectedValue(new Error("save failed"))

    const pending = writingView._runConflictCheck()
    await Promise.resolve()
    showModal.mock.calls[0][2][1].handler()
    await pending

    expect(api.writing.createConflictCheck).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("save failed", "error")
  })

  it("refreshes conflict history after AI review completes in the modal", async () => {
    const rerenderStub = stubMethod(writingView, "_rerender")
    const initialCheck = {
      id: "c1",
      chapter_index: 1,
      include_candidates: false,
      items: [],
    }
    const updatedCheck = {
      ...initialCheck,
      ai_review_status: "done",
      items: [{ id: "i1", is_ai_judgment: true, kind: "motivation_gap" }],
    }
    writingView._conflictChecks = [initialCheck]
    api.context.confirm.mockResolvedValue({
      id: "confirm-ai",
      selected_asset_ids: {},
      warnings: [],
    })
    api.writing.runConflictAiReview.mockResolvedValue(updatedCheck)
    api.writing.listConflictChecks.mockResolvedValue({
      items: [updatedCheck],
      total: 1,
    })
    document.body.innerHTML = `
      <div id="modal-overlay" class="hidden">
        <div id="modal-title"></div>
        <div id="modal-body"></div>
        <div id="modal-footer"></div>
      </div>
    `

    writingView._openConflictCheck("c1")
    document.body.insertAdjacentHTML("beforeend", showModal.mock.calls[0][1])
    document.querySelector("[data-conflict-ai-review]").click()
    await Promise.resolve()
    document.querySelectorAll("#modal-footer button")[1].click()
    for (let i = 0; i < 6; i += 1) await Promise.resolve()

    expect(api.writing.listConflictChecks).toHaveBeenCalledWith({
      novel_id: "p1",
      chapter_index: 1,
      scene_id: "s1",
      limit: 10,
    })
    expect(writingView._latestConflictCheck).toEqual(updatedCheck)
    rerenderStub.mockRestore()
  })

  it("warns before publishing unresolved high severity checks", async () => {
    autoConfirm()
    api.writing.listConflictChecks.mockResolvedValue({
      items: [
        {
          id: "c1",
          summary_json: { open_high_count: 1 },
          items: [{ severity: "high", status: "open" }],
        },
      ],
      total: 1,
    })
    api.writing.publish.mockResolvedValue({
      draft: {
        id: "d2",
        version_number: 3,
        title: "第一章",
        content: "新正文",
      },
    })
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d2", version_number: 3, title: "第一章", word_count: 3 }],
    })
    api.writing.get.mockResolvedValue({
      id: "d2",
      version_number: 3,
      title: "第一章",
      content: "新正文",
    })

    await writingView._publish()

    expect(confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("未处理高严重度问题"),
      expect.any(Function),
      "继续发布",
    )
    expect(api.writing.publish).toHaveBeenCalledWith({
      novel_id: "p1",
      chapter_index: 1,
      scene_id: "s1",
      title: "第一章",
      content: "新正文",
    })
  })

  it("does not warn on publish when high severity items are already resolved", async () => {
    api.writing.listConflictChecks.mockResolvedValue({
      items: [
        {
          id: "c1",
          summary_json: { open_high_count: 1 },
          items: [{ severity: "high", status: "resolved" }],
        },
      ],
      total: 1,
    })
    api.writing.publish.mockResolvedValue({
      draft: {
        id: "d2",
        version_number: 3,
        title: "第一章",
        content: "新正文",
      },
    })
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d2", version_number: 3, title: "第一章", word_count: 3 }],
    })
    api.writing.get.mockResolvedValue({
      id: "d2",
      version_number: 3,
      title: "第一章",
      content: "新正文",
    })

    await writingView._publish()

    expect(confirmAction).not.toHaveBeenCalled()
    expect(api.writing.publish).toHaveBeenCalledWith({
      novel_id: "p1",
      chapter_index: 1,
      scene_id: "s1",
      title: "第一章",
      content: "新正文",
    })
  })

  it("locates conflict items with nested evidence text ranges", () => {
    document.body.innerHTML = '<textarea id="writing-editor">主角死亡。王后沉默。</textarea>'
    const editor = document.getElementById("writing-editor")

    writingView._locateConflictItem(
      {
        items: [
          {
            id: "i1",
            location_json: {
              text_range: { start: 0, end: 4 },
              source: { module: "outline" },
            },
          },
        ],
      },
      "i1",
    )

    expect(editor.selectionStart).toBe(0)
    expect(editor.selectionEnd).toBe(4)
    expect(toast).not.toHaveBeenCalledWith("该问题暂无正文定位", "info")
  })

  it("opens map sources from map_object open target", () => {
    const openMapSpy = stubMethod(writingView, "_openMapForCurrentScene")

    writingView._openConflictSource(
      {
        items: [
          {
            id: "i1",
            location_json: {
              open_target: { kind: "map_object", object_id: "obj1" },
            },
          },
        ],
      },
      "i1",
    )

    expect(openMapSpy).toHaveBeenCalled()
    openMapSpy.mockRestore()
  })

  it("locates text range sources from text_range open target", () => {
    document.body.innerHTML = '<textarea id="writing-editor">主角死亡。王后沉默。</textarea>'
    const editor = document.getElementById("writing-editor")

    writingView._openConflictSource(
      {
        items: [
          {
            id: "i1",
            location_json: {
              open_target: { kind: "text_range" },
              text_range: { start: 5, end: 9 },
            },
          },
        ],
      },
      "i1",
    )

    expect(editor.selectionStart).toBe(5)
    expect(editor.selectionEnd).toBe(9)
    expect(toast).not.toHaveBeenCalledWith("该来源暂无可打开视图", "info")
  })

  it("opens outline sources from outline_scene open target with location hint", () => {
    writingView._openConflictSource(
      {
        items: [
          {
            id: "i1",
            location_json: {
              open_target: { kind: "outline_scene", scene_id: "s1" },
              source: { label: "东门 Scene" },
            },
          },
        ],
      },
      "i1",
    )

    expect(router.navigate).toHaveBeenCalledWith("outline", null)
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("东门 Scene"), "info")
  })

  it("shows memory chapter source modal from memory_chapter open target", () => {
    writingView._openConflictSource(
      {
        items: [
          {
            id: "i1",
            location_json: {
              open_target: {
                kind: "memory_chapter",
                chapter_index: 4,
                character_id: "char-1",
              },
            },
          },
        ],
      },
      "i1",
    )

    expect(showModal).toHaveBeenCalledWith(
      "记忆来源",
      expect.stringContaining("char-1"),
      expect.any(Array),
    )
    expect(showModal.mock.calls[0][1]).toContain("第 4 章")
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
    editor.focus()
    editor.click()
    expect(writingView._cursorOffset).toBe(5)
    expect(document.getElementById("writing-panel-container").innerHTML).toContain("Scene A")
  })

  it("selectionchange updates _cursorOffset and re-renders the panel", () => {
    const editor = document.getElementById("writing-editor")
    editor.selectionStart = 3
    editor.focus()
    document.dispatchEvent(new Event("selectionchange"))
    expect(writingView._cursorOffset).toBe(3)
    expect(document.getElementById("writing-panel-container").innerHTML).toContain("Scene A")
  })

  it("keyup debounces panel update and updates _cursorOffset", () => {
    const editor = document.getElementById("writing-editor")
    editor.selectionStart = 7
    editor.focus()
    document.dispatchEvent(new Event("selectionchange"))
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
    const spy = stubMethod(writingView, "_autosave")
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
    api.imports.startStage
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
    autoConfirm()
    const pollingSpy = vi
      .spyOn(writingView, "_startDeepImportPolling")
      .mockImplementation(() => {})

    await writingView._submitDeepImport(1, 5)

    expect(api.imports.startStage).toHaveBeenNthCalledWith(1, "scenes", "p1", 1, 5, false)
    expect(api.imports.startStage).toHaveBeenNthCalledWith(2, "scenes", "p1", 1, 5, true)
    expect(writingView._deepImportTaskId).toBe("task-2")
    expect(writingView._deepImportProgress.phase).toBe("running")
    expect(writingView._deepImportProgress.workflowType).toBe("scene_auto_extraction")
    expect(JSON.parse(localStorage.getItem(workflowProgressStorageKey))).toEqual([
      expect.objectContaining({
        taskId: "task-2",
        workflowType: "scene_auto_extraction",
        projectId: "p1",
        view: "writing",
      }),
    ])
    expect(pollingSpy).toHaveBeenCalled()

    pollingSpy.mockRestore()
  })
})

describe("_renderDeepImportBar", () => {
  it("显示部分完成和阶段错误原因", () => {
    writingView._deepImportProgress = {
      phase: "done",
      qualityStatus: "partial",
      stepLabel: "完成",
      message: "深度导入完成，但部分阶段降级",
      percent: 100,
      degraded: true,
      phaseErrors: [
        {
          phase: "entity_extraction",
          error_kind: "empty_output",
          message: "实体提取阶段未生成任何实体",
        },
      ],
    }

    const html = writingView._renderDeepImportBar()

    expect(html).toContain("部分完成")
    expect(html).toContain("实体提取阶段未生成任何实体")
  })

  it("recovery_required 时显示明确恢复提示和继续/放弃入口", () => {
    writingView._deepImportTaskId = "deep-task"
    writingView._deepImportProgress = {
      phase: "running",
      message: "worker interrupted",
      percent: 40,
      recoveryRequired: true,
      interrupted: true,
      recoverable: true,
      recoverySummary: {
        last_checkpoint: "phase1b_fusion",
        committed_scenes: 12,
        pending_scene_candidates: 4,
      },
    }

    const html = writingView._renderDeepImportBar()

    expect(html).toContain("需要恢复")
    expect(html).toContain("phase1b_fusion")
    expect(html).toContain("已写入 Scene：12")
    expect(html).toContain("待处理候选：4")
    expect(html).toContain('data-action="resume-deep-import"')
    expect(html).toContain("继续")
    expect(html).toContain('data-action="abandon-deep-import"')
    expect(html).toContain("放弃恢复")
  })

  it("显示当前阶段、章节范围、Scene candidate、window 和 operation", () => {
    writingView._deepImportTaskId = "deep-task"
    writingView._deepImportProgress = {
      phase: "running",
      percent: 35,
      message: "running",
      currentPhase: "phase1b_fusion",
      currentChapterRange: "3-5",
      currentChapter: 4,
      currentSceneCandidateId: "candidate-7",
      currentWindow: "window-2",
      currentOperation: "scene_fusion",
    }

    const html = writingView._renderDeepImportBar()

    expect(html).toContain("阶段：phase1b_fusion")
    expect(html).toContain("章节范围：3-5")
    expect(html).toContain("当前章节：4")
    expect(html).toContain("Scene candidate：candidate-7")
    expect(html).toContain("窗口：window-2")
    expect(html).toContain("操作：scene_fusion")
    expect(html).toContain("deep-import-progress--alive")
  })
})

describe("deep import recovery actions", () => {
  it("继续恢复调用 resume API 并保留原 task id", async () => {
    state.currentProjectId = "p1"
    writingView._deepImportTaskId = "deep-task"
    writingView._deepImportProgress = {
      phase: "running",
      recoveryRequired: true,
      recoverable: true,
      recoverySummary: {},
    }
    api.imports.resumeDeepImport.mockResolvedValue({
      task_id: "deep-task",
      status: "running",
      result: { current_phase: "phase1b_fusion" },
    })
    const pollingSpy = vi
      .spyOn(writingView, "_startDeepImportPolling")
      .mockImplementation(() => {})
    const rerenderSpy = vi.spyOn(writingView, "_rerender").mockImplementation(() => {})

    await writingView._resumeDeepImportRecovery()

    expect(api.imports.resumeDeepImport).toHaveBeenCalledWith("deep-task")
    expect(writingView._deepImportTaskId).toBe("deep-task")
    expect(writingView._deepImportProgress.recoveryRequired).toBe(false)
    expect(pollingSpy).toHaveBeenCalled()
    expect(rerenderSpy).toHaveBeenCalled()

    pollingSpy.mockRestore()
    rerenderSpy.mockRestore()
  })

  it("放弃恢复需要二次确认，取消时不调用 abandon API", async () => {
    writingView._deepImportTaskId = "deep-task"
    writingView._deepImportProgress = { recoveryRequired: true }

    await writingView._abandonDeepImportRecovery()

    expect(confirmAction).toHaveBeenCalled()
    expect(confirmAction.mock.calls[0][0]).toContain("删除/废弃已写入的 Scene/实体")
    expect(api.imports.abandonDeepImport).not.toHaveBeenCalled()
  })

  it("确认放弃恢复后调用 abandon API 并清理本地任务", async () => {
    writingView._deepImportTaskId = "deep-task"
    writingView._deepImportProgress = { recoveryRequired: true }
    localStorage.setItem("novel_deepImportTaskId", "deep-task")
    api.imports.abandonDeepImport.mockResolvedValue({
      status: "cancelled",
      cleanup_summary: { deprecated_scenes: 2, deprecated_entities: 3 },
    })
    autoConfirm()
    const rerenderSpy = vi.spyOn(writingView, "_rerender").mockImplementation(() => {})

    await writingView._abandonDeepImportRecovery()

    expect(api.imports.abandonDeepImport).toHaveBeenCalledWith("deep-task")
    expect(writingView._deepImportTaskId).toBeNull()
    expect(writingView._deepImportProgress).toBeNull()
    expect(localStorage.getItem("novel_deepImportTaskId")).toBeNull()
    expect(toast).toHaveBeenCalledWith("已放弃恢复：Scene 2 个，实体 3 个", "success")
    expect(rerenderSpy).toHaveBeenCalled()

    rerenderSpy.mockRestore()
  })
})

describe("writingView 章节批量操作", () => {
  it("批量删除选中章节并清空当前章状态", async () => {
    state.currentProjectId = "p1"
    writingView._chapterList = [1, 2]
    writingView._chapters = { 1: { title: "一" }, 2: { title: "二" } }
    writingView._currentChapter = 2
    writingView._currentDraftId = "d2"
    writingView._bulkSelections = { "writing-chapters": new Set(["1", "2"]) }
    api.writing.deleteChapter.mockResolvedValue({})
    vi.spyOn(writingView, "_rerender").mockResolvedValue()
    autoConfirm()

    await writingView._runChapterBulkAction("delete-chapters")

    await vi.waitFor(() => {
      expect(api.writing.deleteChapter).toHaveBeenCalledWith(1, "p1")
      expect(api.writing.deleteChapter).toHaveBeenCalledWith(2, "p1")
      expect(writingView._chapterList).toEqual([])
    })
    expect(writingView._currentChapter).toBeNull()
    await vi.waitFor(() => {
      expect(toast).toHaveBeenCalledWith(expect.stringContaining("成功 2 / 2"), "success")
    })
  })
})

describe("_recoverDeepImportTask", () => {
  beforeEach(() => {
    vi.spyOn(writingView, "_rerender").mockImplementation(() => {})
    vi.spyOn(writingView, "_startDeepImportPolling").mockImplementation(() => {})
    localStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("无 localStorage 时不恢复", async () => {
    await writingView._recoverDeepImportTask()
    expect(api.tasks.get).not.toHaveBeenCalled()
  })

  it.each([
    {
      name: "已完成",
      taskId: "task-done",
      response: { status: "done", result: { message: "导入完成: 5 个 Scene" } },
      expectedTaskId: "task-done",
      expectedPhase: "done",
      clearStorage: true,
    },
    {
      name: "运行中",
      taskId: "task-running",
      response: { status: "running", result: { phase: "running", current_step: "entity_extraction", message: "Phase 2/3" } },
      expectedTaskId: "task-running",
      expectedPhase: "running",
      polling: true,
      clearStorage: false,
    },
    {
      name: "失败",
      taskId: "task-failed",
      response: { status: "failed", result: { message: "解析失败" } },
      expectedTaskId: "task-failed",
      expectedPhase: "failed",
      expectedPercent: 0,
      clearStorage: true,
    },
    {
      name: "API 异常",
      taskId: "task-err",
      reject: true,
      clearStorage: true,
    },
  ])("$name task 恢复行为正确", async ({ taskId, response, reject, expectedTaskId, expectedPhase, expectedPercent, polling, clearStorage }) => {
    localStorage.setItem("novel_deepImportTaskId", taskId)
    if (reject) {
      api.tasks.get.mockRejectedValue(new Error("network error"))
    } else {
      api.tasks.get.mockResolvedValue(response)
    }

    await writingView._recoverDeepImportTask()

    if (expectedTaskId !== undefined) {
      expect(writingView._deepImportTaskId).toBe(expectedTaskId)
    }
    if (expectedPhase !== undefined) {
      expect(writingView._deepImportProgress.phase).toBe(expectedPhase)
    }
    if (expectedPercent !== undefined) {
      expect(writingView._deepImportProgress.percent).toBe(expectedPercent)
    }
    if (polling) {
      expect(writingView._startDeepImportPolling).toHaveBeenCalled()
    }
    if (clearStorage) {
      expect(localStorage.getItem("novel_deepImportTaskId")).toBeNull()
      expect(JSON.parse(localStorage.getItem(workflowProgressStorageKey) || "[]")).toEqual([])
    }
  })

  it("可从 shared workflow storage 恢复深度导入任务", async () => {
    localStorage.setItem(workflowProgressStorageKey, JSON.stringify([{
      id: "p1:deep_import:task-shared",
      taskId: "task-shared",
      workflowType: "deep_import",
      projectId: "p1",
      view: "writing",
    }]))
    state.currentProjectId = "p1"
    api.tasks.get.mockResolvedValue({
      status: "running",
      result: { phase: "running", current_step: "entity_extraction", message: "Phase 2/3" },
    })

    await writingView._recoverDeepImportTask()

    expect(api.tasks.get).toHaveBeenCalledWith("task-shared")
    expect(writingView._deepImportTaskId).toBe("task-shared")
    expect(writingView._deepImportProgress.phase).toBe("running")
  })

  it("onActivate 也会触发恢复", async () => {
    localStorage.setItem("novel_deepImportTaskId", "task-reactivate")
    api.tasks.get.mockResolvedValue({
      status: "running",
      result: { phase: "running", current_step: "entity_extraction", message: "Phase 2/3" },
    })
    vi.spyOn(writingView, "_bindEvents").mockImplementation(() => {})
    vi.spyOn(writingView, "_rerender").mockImplementation(() => {})

    await writingView.onActivate()

    expect(api.tasks.get).toHaveBeenCalledWith("task-reactivate")
    expect(writingView._deepImportProgress.phase).toBe("running")
  })
})

describe("workflow progress rendering", () => {
  it("renders publish progress with shared fixed renderer", () => {
    writingView._publishTaskId = "publish-task"
    writingView._publishProgress = {
      phase: "running",
      step: 0.6,
      message: "正在创建历史状态...",
    }

    const html = writingView._renderPublishBar()

    expect(html).toContain("workflow-progress-fixed")
    expect(html).toContain("发布正文")
    expect(html).toContain("60%")
    expect(html).toContain("正在创建历史状态")
  })

  it("renders degraded deep import progress with shared fixed renderer", () => {
    writingView._deepImportTaskId = "deep-task"
    writingView._deepImportProgress = {
      phase: "running",
      percent: 80,
      stepLabel: "Phase 3/3: 结构分析",
      degraded: true,
      degradedBatches: [2],
      qualityStatus: "partial",
      phaseErrors: [{ phase: "entity_extraction", message: "LLM 超时" }],
    }

    const html = writingView._renderDeepImportBar()

    expect(html).toContain("workflow-progress-fixed")
    expect(html).toContain("bottom:40px")
    expect(html).toContain("Phase 3/3: 结构分析")
    expect(html).toContain("部分完成")
    expect(html).toContain("部分批次降级完成")
    expect(html).toContain("降级批次")
    expect(html).toContain("LLM 超时")
  })

  it("renders deep import snapshot health summary when completed", () => {
    writingView._deepImportTaskId = "deep-task"
    writingView._deepImportProgress = {
      phase: "done",
      percent: 100,
      stepLabel: "深度导入完成",
      qualityStatus: "complete",
      snapshotHealthSummary: {
        total_snapshots: 3,
        by_status: {
          running: 0,
          succeeded: 2,
          failed: 1,
        },
        by_phase: {
          entity_extraction: {
            running: 0,
            succeeded: 1,
            failed: 1,
          },
          structure_analysis: {
            running: 0,
            succeeded: 1,
            failed: 0,
          },
        },
        stale_running_count: 1,
        retained_rendered_context_count: 1,
        latest_failure: {
          phase: "entity_extraction",
          scene_index: 8,
          error_kind: "llm_timeout",
        },
      },
    }

    const html = writingView._renderDeepImportBar()

    expect(html).toContain("快照健康摘要")
    expect(html).toContain("共 3 条")
    expect(html).toContain("成功 2")
    expect(html).toContain("失败 1")
    expect(html).toContain("超时 1")
    expect(html).toContain("查看快照状态")
  })
})

describe("_showSplitSceneForm", () => {
  it.each([
    {
      name: "无当前章节时提示",
      setup: () => { writingView._currentChapter = null; writingView._scenes = [] },
      body: "",
      expectedToast: "请先选择章节",
    },
    {
      name: "无当前 Scene 时提示",
      setup: () => { writingView._currentChapter = 1; writingView._scenes = [] },
      body: "",
      expectedToast: "当前章节未关联 Scene",
    },
    {
      name: "无编辑器或内容过短时提示无法断章",
      setup: () => { writingView._currentChapter = 3; writingView._scenes = [{ id: "s1", chapter_ids: ["3"], title: "Scene A" }] },
      body: "",
      expectedToast: "当前章节内容太短，无法断章",
      expectModal: false,
    },
    {
      name: "编辑器内容少于 2 个字符时提示无法断章",
      setup: () => { writingView._currentChapter = 3; writingView._scenes = [{ id: "s1", chapter_ids: ["3"], title: "Scene A" }] },
      body: '<textarea id="writing-editor">a</textarea>',
      expectedToast: "当前章节内容太短，无法断章",
      expectModal: false,
    },
  ])("$name", async ({ setup, body, expectedToast, expectModal }) => {
    setup()
    document.body.innerHTML = body
    await writingView._showSplitSceneForm()
    expect(toast).toHaveBeenCalledWith(expectedToast, "warning")
    if (expectModal === false) {
      expect(showModal).not.toHaveBeenCalled()
    }
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
