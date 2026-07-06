/**
 * writing submodules 工厂最小测试
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createWritingSubModules } from "../../views/writing/submodules.js"
import { confirmAiReference } from "../../shared/aiReferenceModal.js"
import { resetState, clearDocument } from "../helpers.js"

vi.mock("../../shared/aiReferenceModal.js", () => ({
  confirmAiReference: vi.fn(),
}))

function createMockOrchestrator(overrides = {}) {
  return {
    _selectChapter: vi.fn(),
    _selectScene: vi.fn(),
    _onBulkChange: vi.fn(),
    _onWordcountUpdate: vi.fn(),
    _syncSharedStateToSubModules: vi.fn(),
    _rerender: vi.fn(),
    _onVersionSwitch: vi.fn(),
    _onPublished: vi.fn(),
    _onToolsRefresh: vi.fn(),
    _syncChapterMetaToTree: vi.fn(),
    _onSaveStatusChange: vi.fn(),
    _openMap: vi.fn(),
    _onCockpitTabSwitch: vi.fn(),
    _currentChapter: 1,
    _focusMode: false,
    _forceDesktopMode: false,
    _scenePanel: { update: vi.fn(), switchTab: vi.fn() },
    ...overrides,
  }
}

function createMockModal() {
  return {
    showModalHtml: globalThis.showModalHtml,
    showHtml: globalThis.showModalHtml,
    closeModal: globalThis.closeModal,
    close: globalThis.closeModal,
    confirmAction: globalThis.confirmAction,
  }
}

function createDeps(overrides = {}) {
  return {
    state: globalThis.state,
    api: globalThis.api,
    toast: globalThis.toast,
    esc: globalThis.esc,
    modal: createMockModal(),
    router: globalThis.router,
    ...overrides,
  }
}

beforeEach(() => {
  resetState()
  clearDocument()
  localStorage.clear()
  vi.clearAllMocks()
  confirmAiReference.mockReset()
  state._currentChapter = null
  state._currentSceneId = null
  state._scenes = []
  state._chapterList = []
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("createWritingSubModules", () => {
  it("creates all expected submodule instances", () => {
    const orchestrator = createMockOrchestrator()
    const modules = createWritingSubModules(orchestrator, createDeps())

    expect(modules._chapterTree).toBeDefined()
    expect(modules._editor).toBeDefined()
    expect(modules._versions).toBeDefined()
    expect(modules._publish).toBeDefined()
    expect(modules._deepImportRecovery).toBeDefined()
    expect(modules._autoExtraction).toBeDefined()
    expect(modules._conflictCheck).toBeDefined()
    expect(modules._scenePanel).toBeDefined()
    expect(modules._outlineFloat).toBeDefined()
    expect(modules._focusModeManager).toBeDefined()
    expect(modules._tools).toBeDefined()
    expect(modules._mobileQuickNote).toBeDefined()
  })

  it("routes chapterTree selection to orchestrator through public API", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [{ chapter_index: 3, title: "第三章", word_count: 100, version_number: 1 }],
    })
    api.outline.listScenesOrdered.mockResolvedValue([])
    const orchestrator = createMockOrchestrator()
    const modules = createWritingSubModules(orchestrator, createDeps())

    await modules._chapterTree.load()
    document.body.innerHTML = modules._chapterTree.render()
    modules._chapterTree.bindEvents(document.body)
    document.querySelector('[data-action="select-chapter"]').click()

    expect(orchestrator._selectChapter).toHaveBeenCalledWith(3)
  })

  it("routes editor scene change to scenePanel and rerender", async () => {
    state.currentProjectId = "p1"
    state._scenes = [{
      id: "s1",
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 10 }],
    }]
    api.writing.getVersionHistory.mockResolvedValue({ versions: [] })
    api.writing.get.mockResolvedValue({ id: "d1", content: "0123456789", title: "", version_number: 1 })
    const orchestrator = createMockOrchestrator()
    const modules = createWritingSubModules(orchestrator, createDeps())

    await modules._editor.loadChapter(1)
    document.body.innerHTML = modules._editor.render()
    modules._editor.bindEvents(document.body)

    const textarea = document.getElementById("writing-editor")
    textarea.focus()
    textarea.setSelectionRange(5, 5)
    document.dispatchEvent(new Event("selectionchange"))

    expect(orchestrator._syncSharedStateToSubModules).toHaveBeenCalled()
    expect(orchestrator._scenePanel.update).toHaveBeenCalledWith("s1", 1)
    expect(orchestrator._rerender).toHaveBeenCalled()
  })

  it("routes version switch to orchestrator through public API", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({ versions: [{ id: "d1", version_number: 1 }] })
    api.writing.get.mockResolvedValue({ id: "d1", content: "正文", title: "标题", version_number: 1 })
    const orchestrator = createMockOrchestrator()
    const modules = createWritingSubModules(orchestrator, createDeps())

    await modules._versions.load(1)
    await modules._versions.switchVersion("d1", 1, true)

    expect(orchestrator._onVersionSwitch).toHaveBeenCalledWith(expect.objectContaining({
      draftId: "d1",
      versionNumber: 1,
    }))
  })

  it("routes publish status change to editor and rerender", async () => {
    state.currentProjectId = "p1"
    api.writing.publish.mockResolvedValue({ published: true })
    const orchestrator = createMockOrchestrator()
    const modules = createWritingSubModules(orchestrator, createDeps())
    modules._editor.setPublishStatus = vi.fn()

    await modules._publish.publish("正文", "标题", 1, "d1", null)

    expect(modules._editor.setPublishStatus).toHaveBeenCalledWith("发布成功")
    expect(orchestrator._rerender).toHaveBeenCalled()
  })

  it("routes autoExtraction task start to orchestrator", async () => {
    state.currentProjectId = "p1"
    state._chapterList = [1, 2]
    confirmAiReference.mockResolvedValue({ id: "conf-1" })
    api.outline.extractChapterScenes.mockResolvedValue({ task_id: "c1" })
    const orchestrator = createMockOrchestrator()
    orchestrator._onTaskStarted = vi.fn()
    const modules = createWritingSubModules(orchestrator, createDeps())

    await modules._autoExtraction.extractChapterCards()
    const [, , buttons] = showModalHtml.mock.calls[0]
    document.body.innerHTML = `
      <input id="extract-start" value="1" />
      <input id="extract-end" value="2" />
    `
    await buttons[0].handler()

    expect(orchestrator._onTaskStarted).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "c1",
      workflowType: "chapter_card_generation",
    }))
  })

  it("routes focusMode change to orchestrator state through public API", () => {
    document.body.innerHTML = `
      <textarea id="writing-editor"></textarea>
      <div id="writing-tree-container"></div>
      <div id="writing-panel-container"></div>
      <div id="sidebar"></div>
    `
    const orchestrator = createMockOrchestrator()
    const modules = createWritingSubModules(orchestrator, createDeps())

    modules._focusModeManager.toggle()

    expect(orchestrator._focusMode).toBe(true)
    expect(orchestrator._syncSharedStateToSubModules).toHaveBeenCalled()
    expect(orchestrator._rerender).toHaveBeenCalled()
  })

  it("routes mobileQuickNote save to orchestrator through public API", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    state._currentDraftId = "d1"
    state._currentTitle = "第一章"
    api.writing.autosave.mockResolvedValue({ version_number: 2, updated_at: "2026-07-06T10:00:00Z" })
    const orchestrator = createMockOrchestrator()
    const modules = createWritingSubModules(orchestrator, createDeps())

    document.body.innerHTML = modules._mobileQuickNote.render()
    modules._mobileQuickNote.bindEvents(document.body)
    document.querySelector('[data-action="save-mobile-note"]').click()
    await flushPromises()

    expect(orchestrator._syncChapterMetaToTree).toHaveBeenCalledWith(1)
    expect(orchestrator._syncSharedStateToSubModules).toHaveBeenCalled()
    expect(orchestrator._rerender).toHaveBeenCalled()
  })
})

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}
