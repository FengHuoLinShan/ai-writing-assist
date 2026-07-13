import { describe, it, expect, vi, beforeEach } from "vitest"
import { createAutoExtraction } from "../../views/writing/autoExtraction.js"
import { confirmAiReference } from "../../shared/aiReferenceModal.js"
import { resetState, clearDocument } from "../helpers.js"

vi.mock("../../shared/aiReferenceModal.js", () => ({
  confirmAiReference: vi.fn(),
}))

function createMockApi(overrides = {}) {
  return {
    imports: {
      startStage: vi.fn(),
    },
    outline: {
      extractChapterScenes: vi.fn(),
      listScenesOrdered: vi.fn(),
    },
    ...overrides,
  }
}

function createMockModal() {
  return {
    showModalHtml: vi.fn(),
    confirmAction: vi.fn(),
    closeModal: vi.fn(),
  }
}

beforeEach(() => {
  resetState({ currentProjectId: "p1" })
  clearDocument()
  vi.clearAllMocks()
})

describe("createAutoExtraction", () => {
  it("returns the public API", () => {
    const extractor = createAutoExtraction({ api: createMockApi(), esc })
    expect(extractor.showForm).toBeTypeOf("function")
    expect(extractor.extractChapterCards).toBeTypeOf("function")
    expect(extractor.dispose).toBeTypeOf("function")
  })

  it("showForm renders modal with stage label and chapter defaults", () => {
    const modal = createMockModal()
    const extractor = createAutoExtraction({
      state: { currentProjectId: "p1", _chapterList: [1, 2, 3, 5] },
      api: createMockApi(),
      esc,
      modal,
    })

    extractor.showForm("world_objects")

    expect(modal.showModalHtml).toHaveBeenCalled()
    const [title, body] = modal.showModalHtml.mock.calls[0]
    expect(title).toBe("世界对象与别名/关系自动提取")
    expect(body).toContain("auto-extract-start")
    expect(body).toContain("auto-extract-end")
    expect(body).toContain('value="1"')
    expect(body).toContain('value="5"')
    expect(body).toContain("自动采用通过门禁")
    expect(body).toContain("进入待处理")
    expect(modal.showModalHtml.mock.calls[0][2][0].text).toBe("确认并开始提取")
  })

  it("showForm renders the scenes stage", () => {
    const modal = createMockModal()
    const extractor = createAutoExtraction({
      state: { currentProjectId: "p1", _chapterList: [1, 2] },
      api: createMockApi(),
      esc,
      modal,
    })

    extractor.showForm("scenes")

    const [title] = modal.showModalHtml.mock.calls[0]
    expect(title).toBe("场景（scene）自动提取")
  })

  it("submitStage starts task and notifies orchestrator", async () => {
    const api = createMockApi()
    api.imports.startStage.mockResolvedValue({ task_id: "t1" })
    const onTaskStarted = vi.fn()
    const toast = vi.fn()
    const modal = createMockModal()
    const extractor = createAutoExtraction({
      state: { currentProjectId: "p1", _chapterList: [1, 2, 3] },
      api,
      esc,
      toast,
      modal,
      onTaskStarted,
    })

    extractor.showForm("scenes")
    const [, , buttons] = modal.showModalHtml.mock.calls[0]
    document.body.innerHTML = `
      <input id="auto-extract-start" value="1" />
      <input id="auto-extract-end" value="3" />
      <input id="auto-extract-high-quality" type="checkbox" checked />
    `
    await buttons[0].handler()

    expect(api.imports.startStage).toHaveBeenCalledWith(
      "scenes",
      "p1",
      1,
      3,
      false,
      true,
      {
        adoption_policy: "user_authorized_pipeline",
        authorization_confirmed: true,
      },
    )
    expect(onTaskStarted).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "t1",
      workflowType: "scene_auto_extraction",
      stage: "scenes",
      startChapter: 1,
      endChapter: 3,
      highQuality: true,
    }))
    expect(toast).toHaveBeenCalledWith("场景（scene）自动提取已启动", "success")
  })

  it("extractChapterCards confirms AI reference and notifies orchestrator", async () => {
    confirmAiReference.mockResolvedValue({ id: "conf-1" })
    const api = createMockApi()
    api.outline.extractChapterScenes.mockResolvedValue({ task_id: "c1" })
    const modal = createMockModal()
    const onTaskStarted = vi.fn()
    const toast = vi.fn()
    const state = { currentProjectId: "p1", _chapterList: [1, 2] }
    const extractor = createAutoExtraction({
      state,
      api,
      esc,
      modal,
      onTaskStarted,
      toast,
    })

    await extractor.extractChapterCards()
    const [, , buttons] = modal.showModalHtml.mock.calls[0]
    document.body.innerHTML = `
      <input id="extract-start" value="1" />
      <input id="extract-end" value="2" />
    `
    await buttons[0].handler()

    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({
      action: "outline.chapter_scenes.extract",
      include_pending_objects: false,
    }))
    expect(api.outline.extractChapterScenes).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      chapter_index: 1,
      start_chapter: 1,
      end_chapter: 2,
    }))
    expect(onTaskStarted).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "c1",
      workflowType: "outline_chapter_scenes_extract",
      stage: "chapter_cards",
      label: "从正文整理 Scene",
      startChapter: 1,
      endChapter: 2,
      confirmationId: "conf-1",
    }))
    expect(api.outline.listScenesOrdered).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("从正文整理 Scene 已进入后台，完成后需采用", "success")
  })

  it("warns when there are no chapters to extract cards from", () => {
    const toast = vi.fn()
    const extractor = createAutoExtraction({
      state: { currentProjectId: "p1", _chapterList: [] },
      api: createMockApi(),
      esc,
      toast,
    })

    extractor.extractChapterCards()

    expect(toast).toHaveBeenCalledWith("没有可分析的章节", "warning")
  })
})
