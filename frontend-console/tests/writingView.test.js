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
  api.world.getMapSceneSummary = vi.fn()
  vi.clearAllMocks()
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
    autoConfirm()
    const pollingSpy = vi
      .spyOn(writingView, "_startDeepImportPolling")
      .mockImplementation(() => {})

    await writingView._submitDeepImport(1, 5)

    expect(api.imports.deepImport).toHaveBeenNthCalledWith(1, "p1", 1, 5, false)
    expect(api.imports.deepImport).toHaveBeenNthCalledWith(2, "p1", 1, 5, true)
    expect(writingView._deepImportTaskId).toBe("task-2")
    expect(writingView._deepImportProgress.phase).toBe("running")
    expect(JSON.parse(localStorage.getItem(workflowProgressStorageKey))).toEqual([
      expect.objectContaining({
        taskId: "task-2",
        workflowType: "deep_import",
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
