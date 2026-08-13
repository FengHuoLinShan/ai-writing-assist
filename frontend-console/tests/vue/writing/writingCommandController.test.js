import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("../../../shared/aiReferenceModal.js", () => ({
  confirmAiReference: vi.fn(async () => ({ id: "confirmation-1", user_note: "保持克制" })),
}))

import { createWritingCommandController } from "../../../vue/views/writing/controllers/writingCommandController.js"
import { confirmAiReference } from "../../../shared/aiReferenceModal.js"

function setup(overrides = {}) {
  const api = {
    writing: {
      generate: vi.fn(async () => ({ draft_id: "candidate-1" })),
      semanticReview: vi.fn(),
      targetedRevision: vi.fn(),
    },
    tasks: { get: vi.fn() },
  }
  const editor = {
    getCursorOffset: vi.fn(() => 2),
    getContent: vi.fn(() => "甲乙丙丁"),
    getLoadedContent: vi.fn(() => "甲乙丙丁"),
    getTitle: vi.fn(() => "第一章"),
    getDraftId: vi.fn(() => "draft-1"),
    getStatus: vi.fn(() => "working"),
    getProvenance: vi.fn(() => ({})),
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
    getScene: () => ({
      id: "scene-1",
      pov_character_id: "character-1",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 4 }],
    }),
    editor,
    onResult,
    ...overrides,
  })
  return { api, editor, onResult, toast, project, controller }
}

describe("writingCommandController", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()
  })

  it("通过引用确认生成待审正文，不直接写入工作稿", async () => {
    const { api, onResult, controller } = setup()
    await controller.generateDraft()
    expect(api.writing.generate).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      chapter_index: 1,
      context_confirmation_id: "confirmation-1",
    }))
    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({ scene_id: "scene-1" }))
    expect(onResult).toHaveBeenCalledWith({ chapter_index: 1, draft_id: "candidate-1" })
  })

  it("续写只允许基于已保存工作稿", async () => {
    const { api, editor, toast, controller } = setup()
    editor.getContent.mockReturnValue("尚未保存")
    await controller.generateContinuation()
    expect(api.writing.generate).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("未保存"), "warning")
  })

  it("空工作稿不会提交续写任务", async () => {
    const { api, editor, toast, controller } = setup()
    editor.getContent.mockReturnValue("  \n")
    editor.getLoadedContent.mockReturnValue("  \n")
    await controller.generateContinuation()
    expect(api.writing.generate).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("正文为空"), "warning")
  })

  it("正文生成进行中时拒绝重复提交", async () => {
    let resolveGeneration
    const { api, toast, controller } = setup()
    api.writing.generate.mockReturnValue(new Promise((resolve) => { resolveGeneration = resolve }))

    const first = controller.generateContinuation()
    await vi.waitFor(() => expect(api.writing.generate).toHaveBeenCalledTimes(1))
    await controller.generateContinuation()

    expect(api.writing.generate).toHaveBeenCalledTimes(1)
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("正在生成"), "warning")
    resolveGeneration({ draft_id: "candidate-1" })
    await first
  })

  it("任务期间正文变更时不覆盖编辑器，作者可手动查看结果", async () => {
    let resolveTask
    const { api, editor, onResult, controller } = setup()
    api.writing.generate.mockResolvedValue({ task_id: "writing-task" })
    api.tasks.get.mockImplementation(() => new Promise((resolve) => { resolveTask = resolve }))

    const generation = controller.generateDraft()
    await vi.waitFor(() => expect(api.tasks.get).toHaveBeenCalledWith("writing-task", "p1"))
    editor.getContent.mockReturnValue("甲乙丙丁戊")
    resolveTask({ task_id: "writing-task", task_type: "writing_generate", status: "done", result: { draft_id: "candidate-2" } })
    await generation

    expect(onResult).not.toHaveBeenCalled()
    expect(JSON.parse(sessionStorage.getItem("novel_active_workflows_v1"))).toEqual([
      expect.objectContaining({ taskId: "writing-task", workflowType: "writing_generate" }),
    ])
    await controller.openResult()
    expect(onResult).toHaveBeenCalledWith({ chapter_index: 1, draft_id: "candidate-2" })
    expect(JSON.parse(sessionStorage.getItem("novel_active_workflows_v1"))).toEqual([])
  })

  it("任务期间手选 Scene 变更时不自动打开旧上下文结果", async () => {
    let selected = { id: "scene-1" }
    let resolveTask
    const { api, onResult, controller } = setup({ getScene: () => selected })
    api.writing.generate.mockResolvedValue({ task_id: "writing-task" })
    api.tasks.get.mockImplementation(() => new Promise((resolve) => { resolveTask = resolve }))

    const generation = controller.generateDraft()
    await vi.waitFor(() => expect(api.tasks.get).toHaveBeenCalledWith("writing-task", "p1"))
    selected = { id: "scene-2" }
    resolveTask({ task_id: "writing-task", status: "done", result: { draft_id: "candidate-2" } })
    await generation

    expect(onResult).not.toHaveBeenCalled()
    await controller.openResult()
    expect(onResult).toHaveBeenCalledWith({ chapter_index: 1, draft_id: "candidate-2" })
  })

  it("restores a completed result after reload until the author explicitly opens it", async () => {
    sessionStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
      id: "p1:writing_generate:completed-writing-task",
      taskId: "completed-writing-task",
      workflowType: "writing_generate",
      projectId: "p1",
      view: "writing",
      meta: { chapter: 1, mode: "draft" },
    }]))
    const onProgress = vi.fn()
    const { api, controller } = setup({ onProgress })
    api.tasks.get.mockResolvedValue({ task_id: "completed-writing-task", status: "done", result: { draft_id: "candidate-restored" } })

    await expect(controller.recover()).resolves.toBe(true)

    expect(onProgress).toHaveBeenLastCalledWith(expect.objectContaining({
      result: { chapter_index: 1, draft_id: "candidate-restored" },
      progress: expect.objectContaining({ status: "done", terminal: true }),
    }))
    expect(JSON.parse(sessionStorage.getItem("novel_active_workflows_v1"))).toHaveLength(1)
  })

  it("clears a missing generation receipt without replaying the request", async () => {
    const { api, controller } = setup()
    api.writing.generate.mockResolvedValue({ task_id: "missing-writing-task" })
    api.tasks.get.mockRejectedValue(Object.assign(new Error("not found"), { status: 404 }))

    await controller.generateDraft()

    expect(api.writing.generate).toHaveBeenCalledOnce()
    expect(api.tasks.get).toHaveBeenCalledOnce()
    expect(JSON.parse(sessionStorage.getItem("novel_active_workflows_v1") || "[]")).toEqual([])
  })

  it("does not recover another tab's writing receipt", async () => {
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
      id: "p1:writing_generate:other-tab-task",
      taskId: "other-tab-task",
      workflowType: "writing_generate",
      projectId: "p1",
      view: "writing",
      meta: { chapter: 1, mode: "draft" },
    }]))
    const { api, controller } = setup()

    await expect(controller.recover()).resolves.toBe(false)
    expect(api.tasks.get).not.toHaveBeenCalled()
  })

  it("独立语义审查冻结当前候选并重载审查回执", async () => {
    const onProgress = vi.fn()
    const { api, editor, onResult, controller } = setup({ onProgress })
    editor.getStatus.mockReturnValue("candidate")
    api.writing.semanticReview.mockResolvedValue({ task_id: "review-task" })
    api.tasks.get.mockResolvedValue({
      task_id: "review-task",
      task_type: "writing_semantic_review",
      status: "done",
      result: { blocking_count: 1, findings: [{ finding_id: "finding-1" }] },
    })

    await controller.reviewCandidate()

    expect(api.writing.semanticReview).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      draft_ids: ["draft-1"],
      scope: "selection",
    }))
    expect(onResult).toHaveBeenCalledWith({ chapter_index: 1, draft_id: "draft-1" })
    expect(onProgress).toHaveBeenLastCalledWith(expect.objectContaining({
      result: expect.objectContaining({ blocking_count: 1 }),
    }))
  })

  it("废弃历史稿即使只读也不能启动候选审查", async () => {
    const { api, editor, toast, controller } = setup()
    editor.getStatus.mockReturnValue("deprecated")
    editor.isReadonly.mockReturnValue(true)

    await controller.reviewCandidate()

    expect(api.writing.semanticReview).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("请先打开一份待处理正文建议", "warning")
  })

  it("定向返修使用冻结 finding 并打开新候选", async () => {
    const { api, editor, onResult, controller } = setup()
    editor.getStatus.mockReturnValue("candidate")
    editor.getProvenance.mockReturnValue({ independent_review: {
      review_task_id: "00000000-0000-0000-0000-000000000010",
      finding_ids: ["finding-1"],
    } })
    api.writing.targetedRevision.mockResolvedValue({ task_id: "revision-task" })
    api.tasks.get.mockResolvedValue({
      task_id: "revision-task",
      task_type: "writing_targeted_revision",
      status: "done",
      result: { draft_id: "candidate-revised" },
    })

    await controller.reviseCandidate()

    expect(api.writing.targetedRevision).toHaveBeenCalledWith(expect.objectContaining({
      draft_id: "draft-1",
      finding_ids: ["finding-1"],
    }))
    expect(onResult).toHaveBeenCalledWith({ chapter_index: 1, draft_id: "candidate-revised" })
  })

})
