/**
 * conflictCheck 子模块最小测试
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createConflictCheck } from "../../views/writing/conflictCheck.js"
import { resetState, clearDocument } from "../helpers.js"

function createTestChecker(overrides = {}) {
  return createConflictCheck({
    state: globalThis.state,
    api: globalThis.api,
    toast: globalThis.toast,
    modal: {
      showModalHtml: globalThis.showModalHtml,
      confirmAction: globalThis.confirmAction,
      closeModal: globalThis.closeModal,
    },
    esc: globalThis.esc,
    onInsertText: vi.fn(),
    onOpenMap: vi.fn(),
    onNavigateOutline: vi.fn(),
    ...overrides,
  })
}

beforeEach(() => {
  resetState()
  clearDocument()
  vi.clearAllMocks()
  globalThis.showModalHtml.mockReset()
  state._currentChapter = null
  state._currentSceneId = null
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("createConflictCheck", () => {
  it("returns the public API", () => {
    const checker = createTestChecker()
    expect(checker.run).toBeTypeOf("function")
    expect(checker.refresh).toBeTypeOf("function")
    expect(checker.renderStrip).toBeTypeOf("function")
    expect(checker.bindEvents).toBeTypeOf("function")
    expect(checker.open).toBeTypeOf("function")
    expect(checker.dispose).toBeTypeOf("function")
  })

  it("warns when running without project or chapter", async () => {
    const checker = createTestChecker()
    await checker.run(null, () => "正文")
    expect(toast).toHaveBeenCalledWith("请先选择章节", "warning")
  })

  it("runs conflict check with options", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    api.writing.createConflictCheck.mockResolvedValue({ id: "check-1" })
    api.writing.listConflictChecks.mockResolvedValue({ items: [{ id: "check-1", summary_json: { total: 2 } }] })
    globalThis.showModalHtml.mockImplementation((_title, _body, buttons) => {
      setTimeout(() => buttons?.[1]?.handler(), 0)
    })

    const checker = createTestChecker()
    await checker.run(1, () => "正文")
    await flushPromises()

    expect(api.writing.createConflictCheck).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      chapter_index: 1,
      content: "正文",
      include_candidates: false,
    }))
  })

  it("renders empty strip when no chapter selected", () => {
    state._currentChapter = null
    const checker = createTestChecker()
    expect(checker.renderStrip()).toBe("")
  })

  it("renders latest check summary", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    api.writing.listConflictChecks.mockResolvedValue({
      items: [
        { id: "c1", created_at: "2026-07-06T10:00:00Z", summary_json: { total: 3 } },
        { id: "c2", created_at: "2026-07-06T09:00:00Z", summary_json: { total: 1 } },
      ],
    })

    const checker = createTestChecker()
    await checker.refresh(1)
    const html = checker.renderStrip()

    expect(html).toContain("writing-conflict-strip")
    expect(html).toContain("发现 3 个冲突")
    expect(html).toContain('data-check-id="c1"')
    expect(html).toContain("历史")
    expect(html).toContain('data-check-id="c2"')
  })

  it("opens check modal when clicking strip button", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    api.writing.listConflictChecks.mockResolvedValue({
      items: [{ id: "c1", items: [], summary_json: { total: 0 } }],
    })

    const checker = createTestChecker()
    await checker.refresh(1)
    document.body.innerHTML = checker.renderStrip()
    checker.bindEvents(document.body)

    document.querySelector('[data-action="open-conflict-check"]').click()

    expect(showModalHtml).toHaveBeenCalled()
    const call = showModalHtml.mock.calls.find(([title]) => title === "剧情设定冲突检查")
    expect(call).toBeDefined()
    expect(call[1]).toContain("c1")
  })

  it("locates item in editor when text range exists", async () => {
    state.currentProjectId = "p1"
    const checker = createTestChecker()
    document.body.innerHTML = '<textarea id="writing-editor"></textarea>'
    const editor = document.getElementById("writing-editor")
    editor.focus = vi.fn()
    editor.setSelectionRange = vi.fn()

    checker.locateItem({
      items: [{ id: "i1", location_json: { text_range: { start: 5, end: 10 } } }],
    }, "i1")

    expect(editor.focus).toHaveBeenCalled()
    expect(editor.setSelectionRange).toHaveBeenCalledWith(5, 10)
  })

  it("opens map source through callback", async () => {
    state.currentProjectId = "p1"
    const onOpenMap = vi.fn()
    const checker = createTestChecker({ onOpenMap })

    checker.openSource({
      items: [{ id: "i1", location_json: { open_target: { kind: "map_scene" } } }],
    }, "i1")

    expect(onOpenMap).toHaveBeenCalled()
  })

  it("navigates outline source through callback", async () => {
    state.currentProjectId = "p1"
    const onNavigateOutline = vi.fn()
    const checker = createTestChecker({ onNavigateOutline })

    checker.openSource({
      items: [{ id: "i1", location_json: { open_target: { kind: "outline_scene", scene_id: "s1" } } }],
    }, "i1")

    expect(onNavigateOutline).toHaveBeenCalledWith("已打开大纲：s1")
  })

  it("warns when opening missing check", () => {
    const checker = createTestChecker()
    checker.open("missing-id")
    expect(toast).toHaveBeenCalledWith("检查记录暂不可用", "warning")
  })

  it("escapes dynamic content in strip", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    api.writing.listConflictChecks.mockResolvedValue({
      items: [{ id: "<script>", summary_json: { total: 1 } }],
    })

    const checker = createTestChecker()
    await checker.refresh(1)
    const html = checker.renderStrip()

    expect(html).toContain("&lt;script&gt;")
    expect(html).not.toContain('data-check-id="<script>"')
  })

  it("disposes internal state", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    api.writing.listConflictChecks.mockResolvedValue({ items: [{ id: "c1" }] })

    const checker = createTestChecker()
    await checker.refresh(1)
    checker.dispose()

    state._currentChapter = null
    expect(checker.renderStrip()).toBe("")
    checker.open("c1")
    expect(toast).toHaveBeenCalledWith("检查记录暂不可用", "warning")
  })
})

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}
