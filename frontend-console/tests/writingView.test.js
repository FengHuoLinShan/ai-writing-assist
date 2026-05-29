/**
 * writingView 测试
 *
 * 覆盖生命周期、章节选择、草稿操作、版本历史、提取任务和深度导入。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import writingView from "../views/writingView.js"

beforeEach(() => {
  state.currentProjectId = null
  state.currentProject = null
  state.viewStates = {}
  localStorage.removeItem("novel_deep_import_task")
  writingView._deepImportTaskId = null
  writingView._deepImportPhase = "idle"
  writingView._deepImportTimer = null
  writingView._extractionTasks = {}
  writingView._extractionTimer = null
  vi.clearAllMocks()
})

// ============================================================
// Render
// ============================================================

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
    expect(html).toContain("暂无章节")
    expect(html).toContain("data-action=\"nav-chapters\"")
  })

  it("有章节时渲染三栏布局", async () => {
    writingView._loading = false
    writingView._chapterList = [1, 2]
    writingView._chapters = { 1: { hasCard: true, hasDraft: false, cardTitle: "开头", cardStatus: "draft" }, 2: { hasCard: false, hasDraft: true, cardTitle: null, cardStatus: null } }
    const html = await writingView.render()
    expect(html).toContain("章节（2）")
    expect(html).toContain("第 1 章")
    expect(html).toContain("第 2 章")
    expect(html).toContain("writing-editor")
  })
})

// ============================================================
// onEnter
// ============================================================

describe("onEnter", () => {
  it("无项目时设置 loading=false 不调 API", async () => {
    await writingView.onEnter()
    expect(writingView._loading).toBe(false)
    expect(api.outline.listChapterCards).not.toHaveBeenCalled()
    expect(api.writing.listChapters).not.toHaveBeenCalled()
  })

  it("有项目时加载章节卡和草稿索引", async () => {
    state.currentProjectId = "p1"
    api.outline.listChapterCards.mockResolvedValue({
      items: [{ chapter_index: 1, title: "第一章", status: "draft" }],
    })
    api.writing.listChapters.mockResolvedValue({ chapter_indices: [1, 2] })

    await writingView.onEnter()

    expect(api.outline.listChapterCards).toHaveBeenCalledWith({ novel_id: "p1", limit: 50 })
    expect(api.writing.listChapters).toHaveBeenCalledWith("p1")
    expect(writingView._chapterList).toEqual([1, 2])
    expect(writingView._chapters[1]).toEqual({ hasCard: true, hasDraft: true, cardTitle: "第一章", cardStatus: "draft" })
    expect(writingView._chapters[2]).toEqual({ hasCard: false, hasDraft: true, cardTitle: null, cardStatus: null })
  })

  it("API 失败时设置空章节列表", async () => {
    state.currentProjectId = "p1"
    api.outline.listChapterCards.mockRejectedValue(new Error("网络错误"))

    await writingView.onEnter()

    expect(writingView._chapterList).toEqual([])
    expect(writingView._loading).toBe(false)
  })

  it("恢复保存的编辑状态", async () => {
    state.viewStates.writing = {
      currentChapter: 3,
      currentContent: "现有内容",
      currentDraftId: "draft-1",
      currentDraftStatus: "draft",
    }
    state.currentProjectId = "p1"
    api.outline.listChapterCards.mockResolvedValue({ items: [] })
    api.writing.listChapters.mockResolvedValue({ chapter_indices: [] })

    await writingView.onEnter()

    expect(writingView._currentChapter).toBe(3)
    expect(writingView._currentContent).toBe("现有内容")
    expect(writingView._currentDraftId).toBe("draft-1")
    expect(api.outline.getChapterCardByIndex).toHaveBeenCalledWith(3, "p1")
  })

  it("恢复深度导入任务（从 localStorage）", async () => {
    localStorage.setItem("novel_deep_import_task", JSON.stringify({
      taskId: "task-1", projectId: "p1", startChapter: 1, endChapter: 3,
    }))
    state.currentProjectId = "p1"
    api.outline.listChapterCards.mockResolvedValue({ items: [] })
    api.writing.listChapters.mockResolvedValue({ chapter_indices: [] })
    api.tasks.get.mockResolvedValue({ status: "running", result: { phase: "running" } })

    await writingView.onEnter()

    expect(writingView._deepImportTaskId).toBe("task-1")
    expect(api.tasks.get).toHaveBeenCalledWith("task-1")
  })

  it("忽略其他项目的深度导入任务", async () => {
    localStorage.setItem("novel_deep_import_task", JSON.stringify({
      taskId: "task-1", projectId: "other-project",
    }))
    state.currentProjectId = "p1"
    api.outline.listChapterCards.mockResolvedValue({ items: [] })
    api.writing.listChapters.mockResolvedValue({ chapter_indices: [] })

    await writingView.onEnter()

    expect(writingView._deepImportTaskId).toBeNull()
    expect(localStorage.getItem("novel_deep_import_task")).toBeNull()
  })
})

// ============================================================
// onLeave
// ============================================================

describe("onLeave", () => {
  it("保存当前编辑状态", () => {
    writingView._currentChapter = 2
    writingView._currentContent = "正文内容"
    writingView._currentDraftId = "d-1"
    writingView._currentDraftStatus = "candidate"

    writingView.onLeave()

    expect(state.viewStates.writing).toEqual({
      currentChapter: 2,
      currentContent: "正文内容",
      currentDraftId: "d-1",
      currentDraftStatus: "candidate",
    })
  })
})

// ============================================================
// 章节导航
// ============================================================

describe("章节导航", () => {
  beforeEach(() => {
    writingView._chapterList = [1, 2, 3]
    writingView._currentChapter = 2
  })

  describe("_hasPrev", () => {
    it("第一章返回 false", () => {
      writingView._currentChapter = 1
      expect(writingView._hasPrev()).toBe(false)
    })

    it("中间章节返回 true", () => {
      expect(writingView._hasPrev()).toBe(true)
    })
  })

  describe("_hasNext", () => {
    it("最后一章返回 false", () => {
      writingView._currentChapter = 3
      expect(writingView._hasNext()).toBe(false)
    })

    it("中间章节返回 true", () => {
      expect(writingView._hasNext()).toBe(true)
    })
  })

  describe("_prevChapter", () => {
    it("跳转到上一章", () => {
      const spy = vi.spyOn(writingView, "_selectChapter").mockImplementation(() => {})
      writingView._prevChapter()
      expect(spy).toHaveBeenCalledWith(1)
      spy.mockRestore()
    })

    it("第一章不跳转", () => {
      writingView._currentChapter = 1
      const spy = vi.spyOn(writingView, "_selectChapter").mockImplementation(() => {})
      writingView._prevChapter()
      expect(spy).not.toHaveBeenCalled()
      spy.mockRestore()
    })
  })

  describe("_nextChapter", () => {
    it("跳转到下一章", () => {
      const spy = vi.spyOn(writingView, "_selectChapter").mockImplementation(() => {})
      writingView._nextChapter()
      expect(spy).toHaveBeenCalledWith(3)
      spy.mockRestore()
    })

    it("最后一章不跳转", () => {
      writingView._currentChapter = 3
      const spy = vi.spyOn(writingView, "_selectChapter").mockImplementation(() => {})
      writingView._nextChapter()
      expect(spy).not.toHaveBeenCalled()
      spy.mockRestore()
    })
  })
})

// ============================================================
// 草稿操作
// ============================================================

describe("saveDraft", () => {
  it("空内容显示警告", async () => {
    document.body.innerHTML = '<textarea id="writing-editor"></textarea>'
    writingView._currentChapter = 1

    await writingView.saveDraft()

    expect(toast).toHaveBeenCalledWith("草稿内容不能为空", "warning")
  })

  it("调用 API 保存并更新状态", async () => {
    document.body.innerHTML = '<textarea id="writing-editor">正文内容</textarea>'
    state.currentProjectId = "p1"
    writingView._currentChapter = 1
    api.writing.saveDraft.mockResolvedValue({
      id: "draft-1", status: "draft", version_number: 1, updated_at: "2026-01-01T00:00:00Z",
    })

    await writingView.saveDraft()

    expect(api.writing.saveDraft).toHaveBeenCalledWith({
      novel_id: "p1",
      chapter_index: 1,
      title: "第1章",
      content: "正文内容",
    })
    expect(writingView._currentContent).toBe("正文内容")
    expect(writingView._currentDraftId).toBe("draft-1")
    expect(writingView._currentDraftStatus).toBe("draft")
    expect(writingView._currentDraftVersion).toBe(1)
    expect(toast).toHaveBeenCalledWith("草稿已保存", "success")
  })

  it("保存失败时显示错误", async () => {
    document.body.innerHTML = '<textarea id="writing-editor">正文</textarea>'
    state.currentProjectId = "p1"
    writingView._currentChapter = 1
    api.writing.saveDraft.mockRejectedValue(new Error("保存失败"))

    await writingView.saveDraft()

    expect(toast).toHaveBeenCalledWith("保存失败", "error")
  })
})

describe("_updateDraftStatus", () => {
  it("无草稿时显示警告", async () => {
    writingView._currentDraftId = null
    await writingView._updateDraftStatus("candidate")
    expect(toast).toHaveBeenCalledWith("请先保存草稿", "warning")
  })

  it("调用 API 更新状态", async () => {
    writingView._currentDraftId = "d-1"
    state.currentProjectId = "p1"
    api.writing.updateDraftStatus.mockResolvedValue({})

    await writingView._updateDraftStatus("candidate")

    expect(api.writing.updateDraftStatus).toHaveBeenCalledWith("d-1", "candidate", "p1")
    expect(writingView._currentDraftStatus).toBe("candidate")
    expect(toast).toHaveBeenCalledWith("状态已更新为：candidate", "success")
  })

  it("API 失败时显示错误", async () => {
    writingView._currentDraftId = "d-1"
    state.currentProjectId = "p1"
    api.writing.updateDraftStatus.mockRejectedValue(new Error("更新失败"))

    await writingView._updateDraftStatus("canonical")

    expect(toast).toHaveBeenCalledWith("更新失败", "error")
  })
})

describe("_exportDraft", () => {
  it("空内容显示警告", () => {
    document.body.innerHTML = '<textarea id="writing-editor"></textarea>'
    writingView._exportDraft()
    expect(toast).toHaveBeenCalledWith("当前章节没有草稿内容", "warning")
  })
})

// ============================================================
// 版本历史
// ============================================================

describe("_showVersionHistory", () => {
  it("调用 API 并显示 modal", async () => {
    writingView._currentChapter = 1
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [
        { id: "v1", version_number: 1, status: "draft", updated_at: "2026-01-01T00:00:00Z" },
        { id: "v2", version_number: 2, status: "candidate", updated_at: "2026-01-02T00:00:00Z" },
      ],
    })

    await writingView._showVersionHistory()

    expect(api.writing.getVersionHistory).toHaveBeenCalledWith(1, "p1")
    expect(showModal).toHaveBeenCalled()
    const html = vi.mocked(showModal).mock.calls[0][1]
    expect(html).toContain("v1")
    expect(html).toContain("v2")
    expect(html).toContain("data-action=\"restore-version\"")
  })

  it("无版本时显示 info 提示", async () => {
    writingView._currentChapter = 1
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({ versions: [] })

    await writingView._showVersionHistory()

    expect(toast).toHaveBeenCalledWith("该章节暂无历史版本", "info")
  })

  it("API 失败时显示错误", async () => {
    writingView._currentChapter = 1
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockRejectedValue(new Error("请求失败"))

    await writingView._showVersionHistory()

    expect(toast).toHaveBeenCalledWith("无法加载版本历史", "error")
  })
})

// ============================================================
// 提取任务
// ============================================================

describe("_submitWritingExtraction", () => {
  it("无项目时显示警告", async () => {
    await writingView._submitWritingExtraction("world", "world_entity_extraction")
    expect(toast).toHaveBeenCalledWith("请先选择项目", "warning")
  })

  it("提交世界对象抽取任务", async () => {
    state.currentProjectId = "p1"
    document.body.innerHTML = `
      <input id="writing-ext-start" value="1" />
      <input id="writing-ext-end" value="3" />
    `
    api.tasks.submit.mockResolvedValue({ task_id: "task-w1" })

    await writingView._submitWritingExtraction("world", "world_entity_extraction")

    expect(api.tasks.submit).toHaveBeenCalledWith("world_entity_extraction", {
      novel_id: "p1", start_chapter: 1, end_chapter: 3,
    })
    expect(writingView._extractionTasks.world).toEqual({ taskId: "task-w1", status: "running", message: "" })
    expect(toast).toHaveBeenCalledWith("任务已提交", "info")
  })

  it("章节卡提取走确认弹窗", async () => {
    state.currentProjectId = "p1"
    document.body.innerHTML = `
      <input id="writing-ext-start" value="1" />
      <input id="writing-ext-end" value="3" />
    `
    api.outline.listChapterCards.mockResolvedValue({ items: [] })

    // 不会直接提交 tasks.submit
    await writingView._submitWritingExtraction("cards", "chapter_card_extraction")

    expect(showModal).toHaveBeenCalled()
    expect(api.tasks.submit).not.toHaveBeenCalled()
  })

  it("结束章节小于起始章节时显示警告", async () => {
    state.currentProjectId = "p1"
    document.body.innerHTML = `
      <input id="writing-ext-start" value="5" />
      <input id="writing-ext-end" value="3" />
    `

    await writingView._submitWritingExtraction("world", "world_entity_extraction")

    expect(toast).toHaveBeenCalledWith("结束章节必须 ≥ 起始章节", "warning")
  })
})

describe("_pollWritingExtraction", () => {
  it("无运行中任务时清除定时器", async () => {
    writingView._extractionTimer = setInterval(() => {}, 1000)
    writingView._extractionTasks = { world: { status: "done" } }

    await writingView._pollWritingExtraction()

    expect(writingView._extractionTimer).toBeNull()
  })

  it("任务完成时更新状态", async () => {
    writingView._extractionTimer = setInterval(() => {}, 1000)
    writingView._extractionTasks = { world: { taskId: "t-1", status: "running" } }
    api.tasks.getStatus.mockResolvedValue({ status: "done" })

    await writingView._pollWritingExtraction()

    expect(writingView._extractionTasks.world.status).toBe("done")
    expect(toast).toHaveBeenCalled()
  })

  it("任务失败时更新状态", async () => {
    writingView._extractionTimer = setInterval(() => {}, 1000)
    writingView._extractionTasks = { world: { taskId: "t-1", status: "running" } }
    api.tasks.getStatus.mockResolvedValue({ status: "failed", error_message: "超时" })

    await writingView._pollWritingExtraction()

    expect(writingView._extractionTasks.world.status).toBe("failed")
    expect(toast).toHaveBeenCalledWith("步骤失败：超时", "error")
  })
})

// ============================================================
// 深度导入
// ============================================================

describe("深度导入", () => {
  describe("_submitDeepImport", () => {
    it("无项目时显示警告", async () => {
      await writingView._submitDeepImport()
      expect(toast).toHaveBeenCalledWith("请先选择项目", "warning")
    })

    it("提交深度导入并保存到 localStorage", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = `
        <input id="deep-import-start" value="1" />
        <input id="deep-import-end" value="5" />
      `
      api.imports.deepImport.mockResolvedValue({ task_id: "di-1" })
      // 模拟 _updateDeepImportUI 和 _pollDeepImportTask
      const updateUiSpy = vi.spyOn(writingView, "_updateDeepImportUI").mockImplementation(() => {})
      const pollSpy = vi.spyOn(writingView, "_pollDeepImportTask").mockImplementation(() => {})

      await writingView._submitDeepImport()

      expect(api.imports.deepImport).toHaveBeenCalledWith("p1", 1, 5)
      expect(writingView._deepImportTaskId).toBe("di-1")
      expect(writingView._deepImportPhase).toBe("pending")
      expect(localStorage.getItem("novel_deep_import_task")).toContain("di-1")
      expect(toast).toHaveBeenCalledWith("深度导入任务已提交", "success")
      updateUiSpy.mockRestore()
      pollSpy.mockRestore()
    })
  })

  describe("_resumeDeepImport", () => {
    it("继续深度导入并更新 localStorage", async () => {
      writingView._deepImportTaskId = "di-1"
      api.imports.resumeDeepImport.mockResolvedValue({ task_id: "di-2" })
      const stored = JSON.stringify({ taskId: "di-1", projectId: "p1" })
      localStorage.setItem("novel_deep_import_task", stored)
      const updateUiSpy = vi.spyOn(writingView, "_updateDeepImportUI").mockImplementation(() => {})
      const pollSpy = vi.spyOn(writingView, "_pollDeepImportTask").mockImplementation(() => {})

      await writingView._resumeDeepImport()

      expect(api.imports.resumeDeepImport).toHaveBeenCalledWith("di-1")
      expect(writingView._deepImportTaskId).toBe("di-2")
      const updated = JSON.parse(localStorage.getItem("novel_deep_import_task"))
      expect(updated.taskId).toBe("di-2")
      updateUiSpy.mockRestore()
      pollSpy.mockRestore()
    })
  })

  describe("_updateFromTask", () => {
    beforeEach(() => {
      document.body.innerHTML = `
        <div id="deep-import-panel">
          <div id="deep-import-progress" style="display:none;">
            <div id="deep-import-bar"></div>
            <p id="deep-import-status"></p>
          </div>
          <div id="deep-import-steps">
            <div id="step-extract_world"><span class="step-icon">☐</span></div>
            <div id="step-sync_characters"><span class="step-icon">☐</span></div>
            <div id="step-generate_plot"><span class="step-icon">☐</span></div>
          </div>
          <div id="deep-import-actions">
            <button id="btn-deep-goto-review">前往审查</button>
            <button id="btn-deep-resume">继续</button>
            <button id="btn-deep-import-start">开始</button>
          </div>
        </div>
      `
    })

    it("awaiting_review 设置 33% 进度", () => {
      writingView._updateFromTask({
        status: "done",
        result: { phase: "awaiting_review", completed_steps: ["extract_world"] },
      })
      expect(writingView._deepImportPhase).toBe("awaiting_review")
    })

    it("done 阶段设置 100% 进度并清理 localStorage", () => {
      localStorage.setItem("novel_deep_import_task", "stub")
      writingView._updateFromTask({
        status: "done",
        result: { phase: "done", completed_steps: ["extract_world", "sync_characters", "generate_plot"] },
      })
      expect(localStorage.getItem("novel_deep_import_task")).toBeNull()
      expect(toast).toHaveBeenCalledWith("深度导入全部完成！", "success")
    })

    it("failed 状态显示错误", () => {
      writingView._updateFromTask({
        status: "failed",
        error_message: "LLM 调用超时",
        result: {},
      })
      expect(writingView._deepImportPhase).toBe("failed")
      expect(toast).toHaveBeenCalledWith("深度导入失败: LLM 调用超时", "error")
    })
  })

  describe("_gotoReview", () => {
    it("导航到 world 视图并提示", () => {
      writingView._gotoReview()
      expect(router.navigate).toHaveBeenCalledWith("world", "objects")
      expect(toast).toHaveBeenCalledWith("请在「对象库」中审查并确认候选对象", "info")
    })
  })
})

// ============================================================
// 事件绑定
// ============================================================

describe("_bindEvents", () => {
  it("通过 data-action 触发方法", () => {
    const saveSpy = vi.spyOn(writingView, "saveDraft").mockImplementation(() => {})
    document.body.innerHTML = '<div id="workspace-content"><button data-action="save-draft">保存</button></div>'

    writingView._bindEvents()
    document.getElementById("workspace-content").querySelector("button").click()

    expect(saveSpy).toHaveBeenCalled()
    saveSpy.mockRestore()
  })

  it("点击无 data-action 的元素不触发", () => {
    const saveSpy = vi.spyOn(writingView, "saveDraft").mockImplementation(() => {})
    document.body.innerHTML = '<div id="workspace-content"><button>普通按钮</button></div>'

    writingView._bindEvents()
    document.getElementById("workspace-content").querySelector("button").click()

    expect(saveSpy).not.toHaveBeenCalled()
    saveSpy.mockRestore()
  })
})
