import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("../../../shared/aiReferenceModal.js", () => ({
  confirmAiReference: vi.fn(async () => ({ id: "confirmation-1", user_note: "保持克制" })),
}))

import { createWritingCommandController } from "../../../vue/views/writing/controllers/writingCommandController.js"

function setup(overrides = {}) {
  const api = {
    writing: {
      generate: vi.fn(async () => ({ draft_id: "candidate-1" })),
      splitChapter: vi.fn(async () => ({ new_chapter_index: 2 })),
    },
    tasks: { get: vi.fn() },
  }
  const editor = {
    getCursorOffset: vi.fn(() => 2),
    getContent: vi.fn(() => "甲乙丙丁"),
    getLoadedContent: vi.fn(() => "甲乙丙丁"),
    getTitle: vi.fn(() => "第一章"),
    getDraftId: vi.fn(() => "draft-1"),
    isReadonly: vi.fn(() => false),
  }
  const onResult = vi.fn(async () => {})
  const toast = vi.fn()
  const project = { value: "p1" }
  const controller = createWritingCommandController({
    api,
    toast,
    getProjectId: () => project.value,
    getChapter: () => 1,
    getScenes: () => [{
      id: "scene-1",
      pov_character_id: "character-1",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 4 }],
    }],
    editor,
    onResult,
    ...overrides,
  })
  return { api, editor, onResult, toast, project, controller }
}

describe("writingCommandController", () => {
  beforeEach(() => vi.clearAllMocks())

  it("通过引用确认生成待审正文，不直接写入工作稿", async () => {
    const { api, onResult, controller } = setup()
    await controller.generateDraft()
    expect(api.writing.generate).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      chapter_index: 1,
      context_confirmation_id: "confirmation-1",
    }))
    expect(onResult).toHaveBeenCalledWith({ chapter_index: 1, draft_id: "candidate-1" })
  })

  it("续写只允许基于已保存工作稿", async () => {
    const { api, editor, toast, controller } = setup()
    editor.getContent.mockReturnValue("尚未保存")
    await controller.generateContinuation()
    expect(api.writing.generate).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("未保存"), "warning")
  })

  it("断章使用当前 Scene 和光标 offset", async () => {
    const { api, onResult, controller } = setup()
    await controller.splitAtCursor()
    expect(api.writing.splitChapter).toHaveBeenCalledWith(1, {
      split_pos: 2,
      source_scene_id: "scene-1",
    }, "p1")
    expect(onResult).toHaveBeenCalledWith({ new_chapter_index: 2 })
  })
})
