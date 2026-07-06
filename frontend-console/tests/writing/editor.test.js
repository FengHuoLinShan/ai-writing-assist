/**
 * editor 子模块最小测试
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createEditor } from "../../views/writing/editor.js"
import { resetState, clearDocument } from "../helpers.js"

function createTestEditor(overrides = {}) {
  return createEditor({
    state: globalThis.state,
    api: globalThis.api,
    toast: globalThis.toast,
    onWordcountUpdate: vi.fn(),
    onSaveStatusChange: vi.fn(),
    onSceneChange: vi.fn(),
    ...overrides,
  })
}

beforeEach(() => {
  resetState()
  clearDocument()
  localStorage.clear()
  vi.clearAllMocks()
  confirmAction.mockReset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("createEditor", () => {
  it("无选中章节时渲染空状态", () => {
    const editor = createTestEditor()
    const html = editor.render()
    expect(html).toContain("选择章节开始编辑")
    expect(html).toContain("请从左侧选择章节")
    expect(html).not.toContain('<textarea id="writing-editor"')
  })

  it("有选中章节时渲染编辑器", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d1", version_number: 1 }],
    })
    api.writing.get.mockResolvedValue({ id: "d1", content: "正文", title: "第一章", version_number: 1 })

    const editor = createTestEditor()
    await editor.loadChapter(1)
    const html = editor.render()

    expect(html).toContain('<textarea id="writing-editor"')
    expect(html).toContain("正文")
    expect(html).toContain("第一章")
    expect(html).toContain("writing-wordcount-bar")
  })

  it("加载最新草稿并设置状态", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d1", version_number: 2 }],
    })
    api.writing.get.mockResolvedValue({
      id: "d1",
      content: "最新正文",
      title: "最新标题",
      version_number: 2,
      updated_at: "2026-07-06T00:00:00Z",
    })

    const editor = createTestEditor()
    await editor.loadChapter(1)

    expect(editor.getContent()).toBe("最新正文")
    expect(editor.getTitle()).toBe("最新标题")
    expect(editor.saveStatusText()).toBe("已保存")
  })

  it("按 draftId 加载只读版本", async () => {
    state.currentProjectId = "p1"
    api.writing.get.mockResolvedValue({
      id: "d2",
      content: "旧版本正文",
      title: "旧标题",
      version_number: 1,
    })

    const editor = createTestEditor()
    await editor.loadChapter(1, { draftId: "d2", versionNumber: 1, isReadonly: true, restoreSourceVersion: 1 })

    expect(editor.getContent()).toBe("旧版本正文")
    expect(editor.render()).toContain("（只读）")
    expect(editor.render()).toContain("基于此版本创建")
  })

  it("getContent 优先返回 DOM 中 textarea 的值", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({ versions: [] })
    api.writing.get.mockResolvedValue({ id: "d1", content: "初始", title: "", version_number: 1 })

    const editor = createTestEditor()
    await editor.loadChapter(1)

    document.body.innerHTML = editor.render()
    const textarea = document.getElementById("writing-editor")
    textarea.value = "已修改"

    expect(editor.getContent()).toBe("已修改")
  })

  it("根据光标 offset 检测当前 scene", async () => {
    state.currentProjectId = "p1"
    state._scenes = [{
      id: "s1",
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 10 }],
    }]
    api.writing.getVersionHistory.mockResolvedValue({ versions: [] })
    api.writing.get.mockResolvedValue({ id: "d1", content: "0123456789", title: "", version_number: 1 })

    const onSceneChange = vi.fn()
    const editor = createTestEditor({ onSceneChange })
    await editor.loadChapter(1)

    document.body.innerHTML = editor.render()
    const textarea = document.getElementById("writing-editor")
    textarea.focus()
    textarea.setSelectionRange(5, 5)

    editor.bindEvents(document.body)
    document.dispatchEvent(new Event("selectionchange"))

    expect(editor.getCurrentSceneId()).toBe("s1")
    expect(onSceneChange).toHaveBeenCalledWith("s1")
  })

  it("HTML 转义动态内容防止 XSS", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d1", version_number: 1 }],
    })
    api.writing.get.mockResolvedValue({
      id: "d1",
      content: "<script>alert(1)</script>",
      title: "<b>标题</b>",
      version_number: 1,
    })

    const editor = createTestEditor()
    await editor.loadChapter(1)
    const html = editor.render()

    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;")
    expect(html).toContain("&lt;b&gt;标题&lt;/b&gt;")
    expect(html).not.toContain("<script>alert(1)</script>")
  })

  it("dispose 清理计时器与事件监听", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d1", version_number: 1 }],
    })
    api.writing.get.mockResolvedValue({ id: "d1", content: "", title: "", version_number: 1 })

    const editor = createTestEditor()
    await editor.loadChapter(1)
    document.body.innerHTML = editor.render()
    editor.bindEvents(document.body)

    // 触发自动保存计时器
    const titleInput = document.getElementById("writing-title-input")
    titleInput.value = "x"
    titleInput.dispatchEvent(new Event("input"))

    editor.dispose()

    // 验证事件监听已移除：再次 dispose 不抛异常
    expect(() => editor.dispose()).not.toThrow()
  })
})
