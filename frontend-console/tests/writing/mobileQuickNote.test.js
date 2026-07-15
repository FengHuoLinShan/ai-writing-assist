/**
 * mobileQuickNote 子模块最小测试
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createMobileQuickNote } from "../../views/writing/mobileQuickNote.js"
import { resetState, clearDocument } from "../helpers.js"

function createMockEditor(overrides = {}) {
  return {
    getContent: vi.fn(() => "正文内容"),
    getCursorOffset: vi.fn(() => 10),
    setState: vi.fn(),
    ...overrides,
  }
}

function createTestNote(overrides = {}) {
  return createMobileQuickNote({
    state: globalThis.state,
    api: globalThis.api,
    toast: globalThis.toast,
    esc: globalThis.esc,
    editor: createMockEditor(),
    onSaved: vi.fn(),
    ...overrides,
  })
}

beforeEach(() => {
  resetState()
  clearDocument()
  vi.clearAllMocks()
  state._currentChapter = null
  state._currentDraftId = null
  state._currentTitle = null
  state._currentContent = null
  state._currentVersionNumber = null
  state._currentUpdatedAt = null
  state._isReadonly = false
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("createMobileQuickNote", () => {
  it("returns the public API", () => {
    const note = createTestNote()
    expect(note.shouldRender).toBeTypeOf("function")
    expect(note.render).toBeTypeOf("function")
    expect(note.bindEvents).toBeTypeOf("function")
    expect(note.dispose).toBeTypeOf("function")
  })

  it("renders only on narrow viewport with current chapter", () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    vi.stubGlobal("window", { innerWidth: 400 })
    const note = createTestNote()
    expect(note.shouldRender()).toBe(true)
    vi.unstubAllGlobals()
  })

  it("does not render on desktop viewport", () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    vi.stubGlobal("window", { innerWidth: 1200 })
    const note = createTestNote()
    expect(note.shouldRender()).toBe(false)
    vi.unstubAllGlobals()
  })

  it("does not turn a read-only suggestion preview into an editable mobile work draft", () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    state._currentContent = "待处理建议"
    state._isReadonly = true
    vi.stubGlobal("window", { innerWidth: 400 })

    const note = createTestNote()

    expect(note.shouldRender()).toBe(false)
    vi.unstubAllGlobals()
  })

  it("does not render when force-desktop class present", () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    document.body.classList.add("force-desktop")
    vi.stubGlobal("window", { innerWidth: 400 })
    const note = createTestNote()
    expect(note.shouldRender()).toBe(false)
    document.body.classList.remove("force-desktop")
    vi.unstubAllGlobals()
  })

  it("renders mobile note editor", () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    state._currentContent = "灵感片段"
    const note = createTestNote()
    const html = note.render()
    expect(html).toContain("mobile-quick-note")
    expect(html).toContain("mobile-note-editor")
    expect(html).toContain("灵感片段")
    expect(html).toContain('data-action="save-mobile-note"')
  })

  it("autosaves existing draft when save button clicked", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    state._currentDraftId = "d1"
    state._currentVersionNumber = 3
    state._currentUpdatedAt = "2026-07-06T10:00:00Z"
    state._currentTitle = "第一章"
    api.writing.autosave.mockResolvedValue({ version_number: 4, updated_at: "2026-07-06T11:00:00Z" })
    const onSaved = vi.fn()
    const note = createTestNote({ onSaved })

    document.body.innerHTML = note.render()
    document.getElementById("mobile-note-editor").value = "更新内容"
    note.bindEvents(document.body)
    document.querySelector('[data-action="save-mobile-note"]').click()
    await flushPromises()

    expect(api.writing.autosave).toHaveBeenCalledWith(
      "d1",
      expect.objectContaining({ content: "更新内容", expected_version: 3 }),
      "p1",
    )
    expect(onSaved).toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("已保存到工作稿", "success")
  })

  it("creates new draft when save button clicked without current draft id", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 2
    state._currentTitle = "第二章"
    api.writing.autosaveDraftOnly.mockResolvedValue({
      id: "d2",
      version_number: 1,
      updated_at: "2026-07-06T10:00:00Z",
    })

    const editor = createMockEditor()
    const note = createTestNote({ editor })
    document.body.innerHTML = note.render()
    document.getElementById("mobile-note-editor").value = "新内容"
    note.bindEvents(document.body)
    note.bindEvents(document.body)
    document.querySelector('[data-action="save-mobile-note"]').click()
    await flushPromises()

    expect(api.writing.autosaveDraftOnly).toHaveBeenCalledTimes(1)
    expect(api.writing.autosaveDraftOnly).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      chapter_index: 2,
      content: "新内容",
    }))
    expect(editor.setState).toHaveBeenCalledWith(expect.objectContaining({
      draftId: "d2",
      versionNumber: 1,
      updatedAt: "2026-07-06T10:00:00Z",
      lastSavedContent: "新内容",
    }))
  })

  it("首次创建工作稿后连续保存复用新 draft id 和版本", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 2
    state._currentTitle = "第二章"
    api.writing.autosaveDraftOnly.mockResolvedValue({
      id: "d2",
      version_number: 1,
      updated_at: "2026-07-06T10:00:00Z",
    })
    api.writing.autosave.mockResolvedValue({
      id: "d2",
      version_number: 2,
      updated_at: "2026-07-06T10:01:00Z",
    })
    const editor = createMockEditor()
    editor.setState.mockImplementation((patch) => {
      if (patch.draftId !== undefined) state._currentDraftId = patch.draftId
      if (patch.versionNumber !== undefined) state._currentVersionNumber = patch.versionNumber
      if (patch.updatedAt !== undefined) state._currentUpdatedAt = patch.updatedAt
    })
    const note = createTestNote({ editor })
    document.body.innerHTML = note.render()
    note.bindEvents(document.body)

    const editorEl = document.getElementById("mobile-note-editor")
    editorEl.value = "第一次保存"
    document.querySelector('[data-action="save-mobile-note"]').click()
    await flushPromises()
    editorEl.value = "第二次保存"
    document.querySelector('[data-action="save-mobile-note"]').click()
    await flushPromises()

    expect(api.writing.autosaveDraftOnly).toHaveBeenCalledTimes(1)
    expect(api.writing.autosave).toHaveBeenCalledWith(
      "d2",
      expect.objectContaining({
        content: "第二次保存",
        expected_version: 1,
        expected_updated_at: "2026-07-06T10:00:00Z",
      }),
      "p1",
    )
  })

  it("updates word count on input", () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    const editorState = createMockEditor()
    const note = createTestNote({ editor: editorState })
    document.body.innerHTML = note.render()
    note.bindEvents(document.body)

    const editor = document.getElementById("mobile-note-editor")
    editor.value = "一二三四五"
    editor.dispatchEvent(new Event("input"))

    expect(document.getElementById("mobile-note-wc").textContent).toBe("5 字")
    expect(editorState.setState).toHaveBeenCalledWith({ content: "一二三四五" })
  })

  it("does nothing when saving without editor", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    state._currentDraftId = "d1"
    const note = createTestNote()
    note.bindEvents(document.body)
    document.querySelector('[data-action="save-mobile-note"]')?.click()
    await flushPromises()
    expect(api.writing.autosave).not.toHaveBeenCalled()
  })

  it("escapes current content", () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    state._currentContent = "<script>"
    const note = createTestNote()
    const html = note.render()
    expect(html).toContain("&lt;script&gt;")
    expect(html).not.toContain("<script>")
  })
})

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}
