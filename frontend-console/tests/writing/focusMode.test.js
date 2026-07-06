/**
 * focusMode 子模块最小测试
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createFocusModeManager } from "../../views/writing/focusMode.js"
import { resetState, clearDocument } from "../helpers.js"

function createTestManager(overrides = {}) {
  return createFocusModeManager({
    state: globalThis.state,
    onChange: vi.fn(),
    ...overrides,
  })
}

beforeEach(() => {
  resetState()
  clearDocument()
  localStorage.clear()
  vi.clearAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("createFocusModeManager", () => {
  it("returns the public API", () => {
    const manager = createTestManager()
    expect(manager.renderToggle).toBeTypeOf("function")
    expect(manager.toggle).toBeTypeOf("function")
    expect(manager.switchDesktopMode).toBeTypeOf("function")
    expect(manager.isFocusMode).toBeTypeOf("function")
    expect(manager.isForceDesktopMode).toBeTypeOf("function")
    expect(manager.dispose).toBeTypeOf("function")
  })

  it("renders toggle button based on focus state", () => {
    const manager = createTestManager()
    expect(manager.renderToggle()).toContain("专注模式")
    manager.toggle()
    expect(manager.renderToggle()).toContain("退出专注")
  })

  it("toggles focus mode and updates DOM", () => {
    state.currentProjectId = "p1"
    document.body.innerHTML = `
      <textarea id="writing-editor"></textarea>
      <div id="writing-tree-container"></div>
      <div id="writing-panel-container"></div>
      <div id="sidebar"></div>
    `
    const onChange = vi.fn()
    const manager = createTestManager({ onChange })

    manager.toggle()

    expect(manager.isFocusMode()).toBe(true)
    expect(document.body.classList.contains("focus-mode-active")).toBe(true)
    expect(document.getElementById("writing-tree-container").classList.contains("focus-hidden")).toBe(true)
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it("loads default focus mode from localStorage", () => {
    localStorage.setItem("novel_focus_default", "1")
    const manager = createTestManager()
    expect(manager.isFocusMode()).toBe(true)
  })

  it("loads project-specific default focus mode", () => {
    state.currentProjectId = "p1"
    localStorage.setItem("novel_author_preferences:p1", JSON.stringify({ defaultFocusMode: true }))
    const manager = createTestManager()
    expect(manager.isFocusMode()).toBe(true)
  })

  it("switches to desktop mode", () => {
    const onChange = vi.fn()
    const manager = createTestManager({ onChange })
    manager.switchDesktopMode()
    expect(manager.isForceDesktopMode()).toBe(true)
    expect(document.body.classList.contains("force-desktop")).toBe(true)
    expect(onChange).toHaveBeenCalledWith(false, { forceDesktopMode: true })
  })

  it("disposes and resets state", () => {
    const manager = createTestManager()
    manager.toggle()
    manager.switchDesktopMode()
    manager.dispose()
    expect(manager.isFocusMode()).toBe(false)
    expect(manager.isForceDesktopMode()).toBe(false)
  })
})
