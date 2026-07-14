/**
 * versions 子模块最小测试
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createVersionManager } from "../../views/writing/versions.js"
import { resetState, clearDocument } from "../helpers.js"

function createTestManager(overrides = {}) {
  return createVersionManager({
    state: globalThis.state,
    api: globalThis.api,
    toast: globalThis.toast,
    modal: { showHtml: globalThis.showModalHtml, close: globalThis.closeModal },
    esc: globalThis.esc,
    onSwitch: vi.fn(),
    ...overrides,
  })
}

function synchronousModal() {
  return {
    showHtml: (...args) => {
      globalThis.showModalHtml(...args)
      document.body.innerHTML = args[1]
    },
    close: globalThis.closeModal,
  }
}

beforeEach(() => {
  resetState()
  clearDocument()
  vi.clearAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("createVersionManager", () => {
  it("returns the public API", () => {
    const manager = createTestManager()
    expect(manager.load).toBeTypeOf("function")
    expect(manager.render).toBeTypeOf("function")
    expect(manager.bindEvents).toBeTypeOf("function")
    expect(manager.switchVersion).toBeTypeOf("function")
    expect(manager.deleteVersion).toBeTypeOf("function")
    expect(manager.dispose).toBeTypeOf("function")
  })

  it("renders empty when no chapter loaded", () => {
    const manager = createTestManager()
    expect(manager.render()).toBe("")
  })

  it("loads version history and renders selector", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [
        { id: "d2", version_number: 2, status: "draft", version_origin: "manual", word_count: 200, created_at: "2026-07-06T10:00:00Z" },
        { id: "d1", version_number: 1, status: "published", word_count: 100, created_at: "2026-07-05T10:00:00Z" },
      ],
    })

    const manager = createTestManager()
    await manager.load(1)
    const html = manager.render()

    expect(html).toContain("version-selector")
    expect(html).toContain("writing-version-select-wrap")
    expect(html).toContain('aria-label="选择章节版本"')
    expect(html).toContain("v2 (最新)")
    expect(html).toContain("v1")
    expect(html).toContain("手动保存")
    expect(html).toContain("已发布")
    expect(html).toContain('data-action="version-history"')
    expect(html).toContain('data-action="delete-version"')
    expect(html).toContain("publish-status-dot")
  })

  it("keeps review and archived versions out of the main selector", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [
        { id: "candidate-4", version_number: 4, status: "candidate", display_state: "review" },
        { id: "archived-3", version_number: 3, status: "deprecated", display_state: "archived" },
        { id: "working-2", version_number: 2, status: "draft", display_state: "active" },
      ],
    })

    const manager = createTestManager()
    await manager.load(1)
    const html = manager.render()

    expect(html).toContain('value="working-2"')
    expect(html).toContain("v2 (latest)".replace("latest", "最新"))
    expect(html).not.toContain('value="candidate-4"')
    expect(html).not.toContain('value="archived-3"')
  })

  it("shows all history but only active history has restore actions", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [
        { id: "candidate-4", version_number: 4, status: "candidate", display_state: "review" },
        { id: "archived-3", version_number: 3, status: "deprecated", display_state: "archived", deprecated_from_status: "published" },
        { id: "working-2", version_number: 2, status: "draft", display_state: "active" },
        { id: "published-1", version_number: 1, status: "published", display_state: "active" },
      ],
    })

    const manager = createTestManager()
    await manager.load(1)
    document.body.innerHTML = manager.render()
    manager.bindEvents(document.body)
    document.querySelector('[data-action="version-history"]').click()
    const body = showModalHtml.mock.calls.at(-1)[1]

    expect(body).toContain("v4")
    expect(body).toContain("v3")
    expect(body).toContain("v2")
    expect(body).toContain("v1")
    expect(body).toContain("待审核")
    expect(body).toContain("历史 · 原已发布")
    expect(body).not.toContain('version-restore-btn" data-draft-id="candidate-4"')
    expect(body).not.toContain('version-restore-btn" data-draft-id="archived-3"')
    expect(body).toContain('version-restore-btn" data-draft-id="published-1"')
  })

  it("labels archived working history without rendering unknown provenance", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [
        { id: "archived-3", version_number: 3, status: "deprecated", display_state: "archived", deprecated_from_status: "draft" },
        { id: "archived-2", version_number: 2, status: "deprecated", display_state: "archived", deprecated_from_status: '<img src=x onerror="alert(1)">' },
        { id: "working-1", version_number: 1, status: "draft", display_state: "active" },
      ],
    })

    const manager = createTestManager()
    await manager.load(1)
    document.body.innerHTML = manager.render()
    manager.bindEvents(document.body)
    document.querySelector('[data-action="version-history"]').click()
    const body = showModalHtml.mock.calls.at(-1)[1]

    expect(body).toContain("历史 · 原工作稿")
    expect(body).toContain('<span class="pill">历史</span>')
    expect(body).not.toContain("<img")
    expect(body).not.toContain("onerror")
  })

  it("previews archived history read-only using the latest active snapshot", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [
        { id: "archived-3", version_number: 3, status: "deprecated", display_state: "archived" },
        { id: "working-2", version_number: 2, status: "draft", display_state: "active", updated_at: "2026-07-06T00:02:00Z" },
      ],
    })
    api.writing.get.mockResolvedValue({
      id: "archived-3",
      status: "deprecated",
      content: "已归档",
      version_number: 3,
    })
    const onSwitch = vi.fn()
    const manager = createTestManager({ onSwitch, modal: synchronousModal() })
    await manager.load(1)

    await manager.switchVersion("archived-3", 3, false)

    expect(onSwitch).toHaveBeenCalledWith(expect.objectContaining({
      draftId: "archived-3",
      isReadonly: true,
      restoreSourceVersion: null,
      restoreExpectedVersion: null,
      restoreExpectedUpdatedAt: null,
    }))
    expect(manager.render()).not.toContain('data-action="delete-version"')
  })

  it("switches version through selector and notifies orchestrator", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [
        { id: "d2", version_number: 2, updated_at: "2026-07-06T00:02:00Z" },
        { id: "d1", version_number: 1 },
      ],
    })
    api.writing.get.mockImplementation((draftId) => {
      if (draftId === "d1") return Promise.resolve({ id: "d1", content: "旧版本", title: "旧标题", version_number: 1 })
      return Promise.resolve({ id: "d2", content: "最新", title: "最新", version_number: 2 })
    })
    const onSwitch = vi.fn()
    const manager = createTestManager({ onSwitch })

    await manager.load(1)
    document.body.innerHTML = manager.render()
    manager.bindEvents(document.body)

    const select = document.getElementById("version-selector")
    select.selectedIndex = 1
    select.dispatchEvent(new Event("change"))

    await vi.waitFor(() => expect(onSwitch).toHaveBeenCalled())
    expect(onSwitch).toHaveBeenCalledWith(expect.objectContaining({
      draftId: "d1",
      versionNumber: 1,
      isReadonly: true,
      restoreSourceVersion: 1,
      restoreExpectedVersion: 2,
      restoreExpectedUpdatedAt: "2026-07-06T00:02:00Z",
      title: "旧标题",
      content: "旧版本",
    }))
  })

  it("shows version history modal", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d1", version_number: 1, word_count: 100, created_at: "2026-07-06T10:00:00Z" }],
    })

    const manager = createTestManager()
    await manager.load(1)
    document.body.innerHTML = manager.render()
    manager.bindEvents(document.body)

    document.querySelector('[data-action="version-history"]').click()

    expect(showModalHtml).toHaveBeenCalledWith(
      "第 1 章 — 版本历史 (1)",
      expect.stringContaining("v1"),
    )
  })

  it("binds version history preview without window.writingView", async () => {
    const previousWritingView = window.writingView
    window.writingView = undefined
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [
        { id: "d2", version_number: 2, word_count: 200, created_at: "2026-07-06T10:00:00Z" },
        { id: "d1", version_number: 1, word_count: 100, created_at: "2026-07-05T10:00:00Z" },
      ],
    })
    api.writing.get.mockResolvedValue({
      id: "d1",
      content: "旧版本",
      title: "旧标题",
      version_number: 1,
    })
    const onSwitch = vi.fn()
    const manager = createTestManager({ onSwitch, modal: synchronousModal() })

    try {
      await manager.load(1)
      document.body.innerHTML = manager.render()
      manager.bindEvents(document.body)
      document.querySelector('[data-action="version-history"]').click()
      const body = showModalHtml.mock.calls.at(-1)[1]
      expect(body).not.toContain("window.writingView")
      expect(body).not.toContain("onclick=")
      expect(document.body.innerHTML).toContain("version-preview-btn")

      document.querySelector('.version-preview-btn[data-draft-id="d1"]').click()

      await vi.waitFor(() => expect(onSwitch).toHaveBeenCalledWith(expect.objectContaining({
        draftId: "d1",
        versionNumber: 1,
        isReadonly: true,
        restoreSourceVersion: 1,
      })))
      expect(api.writing.get).toHaveBeenCalledWith("d1", "p1")
    } finally {
      window.writingView = previousWritingView
    }
  })

  it("binds version history restore without global orchestrator coupling", async () => {
    const previousWritingView = window.writingView
    window.writingView = undefined
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [
        { id: "d2", version_number: 2, updated_at: "2026-07-06T00:02:00Z" },
        { id: "d1", version_number: 1 },
      ],
    })
    api.writing.get.mockResolvedValue({
      id: "d1",
      content: "旧版本",
      title: "旧标题",
      version_number: 1,
    })
    globalThis.confirmAction.mockImplementation((_message, onConfirm) => onConfirm())
    const onSwitch = vi.fn()
    const manager = createTestManager({ onSwitch, modal: synchronousModal() })

    try {
      await manager.load(1)
      document.body.innerHTML = manager.render()
      manager.bindEvents(document.body)
      document.querySelector('[data-action="version-history"]').click()

      document.querySelector('.version-restore-btn[data-draft-id="d1"]').click()

      expect(confirmAction).toHaveBeenCalledWith(
        "恢复至 v1？当前编辑器内容将丢失。",
        expect.any(Function),
        "确认恢复",
      )
      await vi.waitFor(() => expect(onSwitch).toHaveBeenCalledWith(expect.objectContaining({
        draftId: "d1",
        versionNumber: 1,
        isReadonly: false,
        restoreSourceVersion: 1,
        restoreExpectedVersion: 2,
        restoreExpectedUpdatedAt: "2026-07-06T00:02:00Z",
      })))
    } finally {
      window.writingView = previousWritingView
    }
  })

  it("warns when deleting the only version", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d1", version_number: 1 }],
    })
    api.writing.get.mockResolvedValue({ id: "d1", content: "", title: "", version_number: 1 })
    const manager = createTestManager()
    await manager.load(1)
    await manager.switchVersion("d1", 1, true)
    await manager.deleteVersion()
    expect(toast).toHaveBeenCalledWith("不能删除唯一版本", "warning")
  })

  it("warns when deleting the latest version", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [
        { id: "d2", version_number: 2 },
        { id: "d1", version_number: 1 },
      ],
    })
    api.writing.get.mockResolvedValue({ id: "d2", content: "", title: "", version_number: 2 })
    const manager = createTestManager()
    await manager.load(1)
    await manager.switchVersion("d2", 2, true)
    await manager.deleteVersion()
    expect(toast).toHaveBeenCalledWith("不能删除最新版本", "warning")
  })

  it("deletes non-latest version and switches to latest after confirm", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValueOnce({
      versions: [
        { id: "d2", version_number: 2 },
        { id: "d1", version_number: 1 },
      ],
    }).mockResolvedValueOnce({
      versions: [{ id: "d2", version_number: 2 }],
    })
    api.writing.get.mockImplementation((draftId) => {
      if (draftId === "d1") return Promise.resolve({ id: "d1", content: "旧", title: "旧", version_number: 1 })
      return Promise.resolve({ id: "d2", content: "最新", title: "最新", version_number: 2 })
    })
    api.writing.deleteDraft.mockResolvedValue({})
    vi.stubGlobal("confirm", vi.fn(() => true))

    const manager = createTestManager()
    await manager.load(1)
    await manager.switchVersion("d1", 1, false)
    await manager.deleteVersion()

    expect(api.writing.deleteDraft).toHaveBeenCalledWith("d1", "p1")
    expect(toast).toHaveBeenCalledWith("版本已删除", "success")
  })

  it("escapes dynamic content in version selector", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "<b>", version_number: 1, word_count: 100 }],
    })
    const manager = createTestManager()
    await manager.load(1)
    const html = manager.render()
    expect(html).toContain("&lt;b&gt;")
    expect(html).not.toContain('value="<b>"')
  })

  it("disposes internal state", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d1", version_number: 1 }],
    })
    const manager = createTestManager()
    await manager.load(1)
    manager.dispose()
    expect(manager.render()).toBe("")
  })
})
