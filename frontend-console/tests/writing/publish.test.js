/**
 * publish 子模块最小测试
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createPublishManager } from "../../views/writing/publish.js"
import { resetState, clearDocument } from "../helpers.js"

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

function createTestManager(overrides = {}) {
  return createPublishManager({
    state: globalThis.state,
    api: globalThis.api,
    toast: globalThis.toast,
    modal: { showHtml: globalThis.showModalHtml, close: globalThis.closeModal },
    esc: globalThis.esc,
    onStatusChange: vi.fn(),
    onPublished: vi.fn(),
    ...overrides,
  })
}

beforeEach(() => {
  resetState()
  clearDocument()
  localStorage.clear()
  vi.clearAllMocks()
  state._restoreSourceVersion = null
  state._restoreExpectedVersion = null
  state._restoreExpectedUpdatedAt = null
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe("createPublishManager", () => {
  it("returns the public API", () => {
    const manager = createTestManager()
    expect(manager.publish).toBeTypeOf("function")
    expect(manager.retry).toBeTypeOf("function")
    expect(manager.renderBar).toBeTypeOf("function")
    expect(manager.updateBar).toBeTypeOf("function")
    expect(manager.dismissError).toBeTypeOf("function")
    expect(manager.dispose).toBeTypeOf("function")
  })

  it("renders empty bar when no publish in progress", () => {
    const manager = createTestManager()
    expect(manager.renderBar()).toBe("")
  })

  it("warns when publishing empty content", async () => {
    state.currentProjectId = "p1"
    const manager = createTestManager()
    await manager.publish("   ", "标题", 1, "d1", null)
    expect(toast).toHaveBeenCalledWith("工作稿内容不能为空", "warning")
    expect(api.writing.publish).not.toHaveBeenCalled()
  })

  it("publishes immediately when no task_id returned", async () => {
    state.currentProjectId = "p1"
    api.writing.publish.mockResolvedValue({ published: true })
    const onStatusChange = vi.fn()
    const onPublished = vi.fn()
    const manager = createTestManager({ onStatusChange, onPublished })

    const result = await manager.publish("正文", "标题", 1, "d1", null)

    expect(api.writing.publish).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      chapter_index: 1,
      title: "标题",
      content: "正文",
    }))
    expect(onStatusChange).toHaveBeenCalledWith("发布成功")
    expect(onPublished).toHaveBeenCalledWith(result)
  })

  it("keeps local formatting edits when backend reuses published version", async () => {
    state.currentProjectId = "p1"
    api.writing.publish.mockResolvedValue({ new_version: false, task_id: null })
    const onStatusChange = vi.fn()
    const onPublished = vi.fn()
    const manager = createTestManager({ onStatusChange, onPublished })

    await manager.publish(" 正文 ", "标题", 1, "d1", null, 1, "2026-07-12T00:00:00Z")

    expect(onPublished).not.toHaveBeenCalled()
    expect(onStatusChange).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("正文无实质变化，已沿用当前发布版本", "info")
  })

  it("publishes a restored version against the latest history snapshot", async () => {
    state.currentProjectId = "p1"
    state._restoreSourceVersion = 1
    state._restoreExpectedVersion = 3
    state._restoreExpectedUpdatedAt = "2026-07-03T00:00:00Z"
    api.writing.publish.mockResolvedValue({ task_id: null, new_version: true })
    const manager = createTestManager()

    await manager.publish(
      "恢复内容",
      "标题",
      1,
      "d1",
      null,
      1,
      "2026-07-01T00:00:00Z",
    )

    expect(api.writing.publish).toHaveBeenCalledWith(expect.objectContaining({
      draft_id: "d1",
      restore_source_version: 1,
      expected_version: 3,
      expected_updated_at: "2026-07-03T00:00:00Z",
    }))
  })

  it("retries restoration with the snapshot captured by the first request", async () => {
    state.currentProjectId = "p1"
    state._restoreSourceVersion = 1
    state._restoreExpectedVersion = 3
    state._restoreExpectedUpdatedAt = "2026-07-03T00:00:00Z"
    api.writing.publish.mockResolvedValue({ task_id: null, new_version: true })
    const manager = createTestManager()

    await manager.publish("恢复内容", "标题", 1, "d1", null, 1, null)
    state._restoreSourceVersion = 2
    state._restoreExpectedVersion = 9
    state._restoreExpectedUpdatedAt = "2026-07-09T00:00:00Z"
    await manager.retry()

    expect(api.writing.publish).toHaveBeenLastCalledWith(expect.objectContaining({
      restore_source_version: 1,
      expected_version: 3,
      expected_updated_at: "2026-07-03T00:00:00Z",
    }))
  })

  it("restore conflict reports an error without publishing success", async () => {
    state.currentProjectId = "p1"
    state._restoreSourceVersion = 1
    state._restoreExpectedVersion = 2
    api.writing.publish.mockRejectedValue({ status: 409, message: "该章节已被其他会话更新" })
    const onStatusChange = vi.fn()
    const onPublished = vi.fn()
    const manager = createTestManager({ onStatusChange, onPublished })

    await manager.publish("恢复内容", "标题", 1, "d1", null, 1, null)

    expect(toast).toHaveBeenCalledWith("该章节已被其他会话更新", "error")
    expect(onStatusChange).toHaveBeenCalledWith("发布失败")
    expect(onStatusChange).not.toHaveBeenCalledWith("发布成功")
    expect(onPublished).not.toHaveBeenCalled()
  })

  it("starts polling when task_id returned", async () => {
    vi.useFakeTimers()
    state.currentProjectId = "p1"
    api.writing.publish.mockResolvedValue({ task_id: "task-1" })
    api.tasks.get.mockResolvedValue({
      task_id: "task-1",
      task_type: "publish_chapter",
      status: "done",
      progress: 1,
    })
    const onStatusChange = vi.fn()
    const onPublished = vi.fn()
    const manager = createTestManager({ onStatusChange, onPublished })

    await manager.publish("正文", "标题", 1, "d1", null)
    await vi.advanceTimersByTimeAsync(100)

    expect(api.tasks.get).toHaveBeenCalledWith("task-1", "p1")
    expect(onStatusChange).toHaveBeenCalledWith("发布成功")
  })

  it("shows error modal when publish task fails", async () => {
    vi.useFakeTimers()
    state.currentProjectId = "p1"
    api.writing.publish.mockResolvedValue({ task_id: "task-2" })
    api.tasks.get.mockResolvedValue({
      task_id: "task-2",
      task_type: "publish_chapter",
      status: "failed",
      error_message: "RAG 索引失败",
    })
    const manager = createTestManager()

    await manager.publish("正文", "标题", 1, "d1", null)
    await vi.advanceTimersByTimeAsync(100)

    expect(showModalHtml).toHaveBeenCalledWith("发布失败", expect.stringContaining("RAG 索引失败"))
  })

  it("retries last publish", async () => {
    state.currentProjectId = "p1"
    api.writing.publish.mockResolvedValue({ published: true })
    const manager = createTestManager()

    await manager.publish("正文", "标题", 1, "d1", null)
    await manager.retry()

    expect(api.writing.publish).toHaveBeenCalledTimes(2)
  })

  it("dismisses error and clears progress", async () => {
    state.currentProjectId = "p1"
    api.writing.publish.mockResolvedValue({ published: true })
    const onStatusChange = vi.fn()
    const manager = createTestManager({ onStatusChange })

    await manager.publish("正文", "标题", 1, "d1", null)
    manager.dismissError()

    expect(manager.renderBar()).toBe("")
    expect(onStatusChange).toHaveBeenLastCalledWith(null)
  })

  it("disposes timer and state", async () => {
    vi.useFakeTimers()
    state.currentProjectId = "p1"
    api.writing.publish.mockResolvedValue({ task_id: "task-3" })
    api.tasks.get.mockResolvedValue({
      task_id: "task-3",
      task_type: "publish_chapter",
      status: "running",
      progress: 0.2,
    })
    const manager = createTestManager()

    await manager.publish("正文", "标题", 1, "d1", null)
    manager.dispose()

    expect(manager.renderBar()).toBe("")
  })
})
