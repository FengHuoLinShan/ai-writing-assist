/**
 * tools 子模块最小测试
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createWritingTools } from "../../views/writing/tools.js"
import { confirmAiReference } from "../../shared/aiReferenceModal.js"
import { resetState, clearDocument } from "../helpers.js"

vi.mock("../../shared/aiReferenceModal.js", () => ({
  confirmAiReference: vi.fn(),
}))

function createMockEditor(overrides = {}) {
  return {
    getContent: vi.fn(() => "正文内容"),
    getCursorOffset: vi.fn(() => 10),
    insertTextAtCursor: vi.fn(),
    ...overrides,
  }
}

function createTestTools(overrides = {}) {
  return createWritingTools({
    state: globalThis.state,
    api: globalThis.api,
    toast: globalThis.toast,
    modal: {
      showModalHtml: globalThis.showModalHtml,
      closeModal: globalThis.closeModal,
      confirmAction: globalThis.confirmAction,
    },
    esc: globalThis.esc,
    editor: createMockEditor(),
    onInsertText: vi.fn(),
    onRefresh: vi.fn(),
    ...overrides,
  })
}

beforeEach(() => {
  resetState()
  clearDocument()
  localStorage.clear()
  vi.clearAllMocks()
  confirmAiReference.mockReset()
  state._currentChapter = null
  state._currentTitle = null
  state._currentContent = null
  state._isReadonly = false
  state._scenes = []
  api.writing.generate.mockReset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("createWritingTools", () => {
  it("returns the public API", () => {
    const tools = createTestTools()
    expect(tools.renderToolsMenu).toBeTypeOf("function")
    expect(tools.bindEvents).toBeTypeOf("function")
    expect(tools.exportChapter).toBeTypeOf("function")
    expect(tools.splitScene).toBeTypeOf("function")
    expect(tools.generateDraft).toBeTypeOf("function")
    expect(tools.generatePovDraft).toBeTypeOf("function")
    expect(tools.dispose).toBeTypeOf("function")
  })

  it("renders tools menu with extraction buttons when project exists", () => {
    state.currentProjectId = "p1"
    state._chapterList = [1, 2]
    const tools = createTestTools()
    const html = tools.renderToolsMenu(false)
    expect(html).toContain("AI 工具")
    expect(html).toContain('data-action="ai-generate-pov-draft"')
    expect(html).toContain('data-action="auto-extract-stage"')
    expect(html).toContain('data-action="extract-cards"')
    expect(html).toContain('data-action="open-map"')
  })

  it("disables AI generate draft when no selection or readonly", () => {
    state.currentProjectId = "p1"
    state._isReadonly = false
    const tools = createTestTools()
    const htmlNoSelection = tools.renderToolsMenu(false)
    expect(htmlNoSelection).toContain('data-action="ai-generate-draft" disabled')

    state._isReadonly = true
    const htmlReadonly = tools.renderToolsMenu(true)
    expect(htmlReadonly).toContain('data-action="ai-generate-draft" disabled')
  })

  it("exports chapter as downloadable text file", () => {
    state.currentProjectId = "p1"
    state._currentTitle = "第一章"
    state._currentChapter = 1
    const tools = createTestTools()
    tools.exportChapter()
    expect(toast).toHaveBeenCalledWith("已导出「第一章」", "success")
  })

  it("splits scene through public splitScene method", async () => {
    state.currentProjectId = "p1"
    api.writing.splitChapter.mockResolvedValue({ new_chapter_index: 2 })
    const onRefresh = vi.fn()
    const tools = createTestTools({ onRefresh })

    await tools.splitScene(10, 1, { id: "s1", title: "Scene 1" })

    expect(api.writing.splitChapter).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ split_pos: 10, source_scene_id: "s1" }),
      "p1",
    )
    expect(onRefresh).toHaveBeenCalledWith(expect.objectContaining({ new_chapter_index: 2 }))
    expect(toast).toHaveBeenCalledWith("断章完成", "success")
  })

  it("binds split scene button", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    state._scenes = [{ id: "s1", title: "Scene 1", chapter_ids: ["1"] }]
    api.writing.splitChapter.mockResolvedValue({ new_chapter_index: 2 })
    globalThis.showModalHtml.mockImplementation((_title, body, buttons) => {
      document.body.innerHTML = body
      setTimeout(() => buttons?.[0]?.handler(), 0)
    })
    const tools = createTestTools({ editor: createMockEditor({ getCursorOffset: () => 1 }) })
    const html = tools.renderToolsMenu(false)
    document.body.innerHTML = html
    tools.bindEvents(document.body)

    document.querySelector('[data-action="split-scene"]').click()
    await flushPromises()

    expect(api.writing.splitChapter).toHaveBeenCalled()
  })

  it("generates AI draft", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    confirmAiReference.mockResolvedValue({ id: "conf-1", user_note: "加快速度" })
    api.writing.generate.mockResolvedValue({ task_id: "task-1" })

    const tools = createTestTools()
    await tools.generateDraft()

    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({
      action: "writing.generate",
      include_pending_objects: false,
    }))
    expect(api.writing.generate).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      chapter_index: 1,
      instruction: "加快速度",
      context_confirmation_id: "conf-1",
    }))
    expect(toast).toHaveBeenCalledWith("AI 正文建议任务已提交：task-1", "success")
  })

  it("generates AI POV draft from current Scene viewpoint character", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    state._currentTitle = "第一章"
    state._scenes = [{
      id: "scene-1",
      title: "Scene 1",
      chapter_ids: ["1"],
      pov_character_id: "char-1",
    }]
    confirmAiReference.mockResolvedValue({ id: "conf-pov", user_note: "压低情绪" })
    api.writing.generate.mockResolvedValue({ task_id: "task-pov" })

    const tools = createTestTools()
    await tools.generatePovDraft()

    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      action: "writing.generate",
      task: "基于当前 Scene 的 POV 角色有限认知，生成正文建议预览",
      scope: "chapter",
      chapter_index: 1,
      scene_id: "scene-1",
      reveal_mode: "character",
      viewpoint_character_id: "char-1",
      character_ids: ["char-1"],
      include_pending_objects: false,
    }))
    expect(api.writing.generate).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      chapter_index: 1,
      title: "第一章",
      context_confirmation_id: "conf-pov",
    }))
    const instruction = api.writing.generate.mock.calls[0][0].instruction
    expect(instruction).toContain("压低情绪")
    expect(instruction).toContain("POV 角色有限认知")
    expect(instruction).toContain("角色判断、台词、内心和行动只能使用确认上下文中该角色可见的信息")
    expect(toast).toHaveBeenCalledWith("AI 角色视角建议任务已提交：task-pov", "success")
  })

  it("does not use a readonly suggestion preview as working generation context", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    state._isReadonly = true
    const tools = createTestTools()

    await tools.generateDraft()

    expect(confirmAiReference).not.toHaveBeenCalled()
    expect(api.writing.generate).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("当前内容只读；待处理建议不会作为工作稿参考", "warning")
  })

  it("stops POV draft generation when current Scene is unavailable", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    state._scenes = []

    const tools = createTestTools()
    await tools.generatePovDraft()

    expect(toast).toHaveBeenCalledWith("当前章节未关联 Scene", "warning")
    expect(confirmAiReference).not.toHaveBeenCalled()
    expect(api.writing.generate).not.toHaveBeenCalled()
  })

  it("stops POV draft generation when current Scene has no POV character", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    state._scenes = [{ id: "scene-1", title: "Scene 1", chapter_ids: ["1"] }]

    const tools = createTestTools()
    await tools.generatePovDraft()

    expect(toast).toHaveBeenCalledWith("当前 Scene 未设置 POV 角色", "warning")
    expect(confirmAiReference).not.toHaveBeenCalled()
    expect(api.writing.generate).not.toHaveBeenCalled()
  })

  it("does not submit POV draft when AI reference confirmation is cancelled", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    state._scenes = [{
      id: "scene-1",
      title: "Scene 1",
      chapter_ids: ["1"],
      pov_character_id: "char-1",
    }]
    confirmAiReference.mockRejectedValue(new Error("已取消 AI 参考资料确认"))

    const tools = createTestTools()
    await tools.generatePovDraft()

    expect(api.writing.generate).not.toHaveBeenCalled()
  })

  it("warns when generating draft without chapter", async () => {
    state.currentProjectId = "p1"
    confirmAiReference.mockResolvedValue({ id: "conf-1" })
    api.writing.generate.mockResolvedValue({ task_id: "task-1" })
    const tools = createTestTools()
    await tools.generateDraft()
    expect(toast).toHaveBeenCalledWith("请先选择章节", "warning")
  })

  it("escapes disabled title hint", () => {
    state.currentProjectId = "p1"
    state._isReadonly = true
    const tools = createTestTools()
    const html = tools.renderToolsMenu(true)
    expect(html).toContain("当前版本只读，需基于此版本创建后再使用")
  })
})

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}
