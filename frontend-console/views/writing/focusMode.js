/**
 * 专注模式管理器
 *
 * 负责专注模式切换、桌面模式切换与相关 UI 状态更新。
 */

export function createFocusModeManager({ state, onChange }) {
  const projectState = state

  let focusMode = getFocusDefault()
  let forceDesktopMode = false

  function loadAuthorPreferences() {
    if (projectState._authorPreferences) return projectState._authorPreferences
    try {
      const raw = localStorage.getItem(`novel_author_preferences:${projectState.currentProjectId || "global"}`)
      return raw ? JSON.parse(raw) : {}
    } catch {
      return {}
    }
  }

  function getFocusDefault() {
    try {
      const prefs = loadAuthorPreferences()
      if (typeof prefs.defaultFocusMode === "boolean") return prefs.defaultFocusMode
      return localStorage.getItem("novel_focus_default") === "1"
    } catch {
      return false
    }
  }

  function renderToggle() {
    return `<button class="btn btn-sm" data-action="toggle-focus-mode" title="专注模式（隐藏两侧面板）">${focusMode ? "退出专注" : "专注模式"}</button>`
  }

  function toggle() {
    focusMode = !focusMode
    const editor = document.getElementById("writing-editor")
    document.body.classList.toggle("focus-mode-active", focusMode)
    editor?.classList.toggle("novel-editor--focus", focusMode)
    for (const id of ["writing-tree-container", "writing-panel-container", "sidebar"]) {
      document.getElementById(id)?.classList.toggle("focus-hidden", focusMode)
    }
    editor?.focus()
    onChange?.(focusMode)
  }

  function switchDesktopMode() {
    forceDesktopMode = true
    document.body.classList.add("force-desktop")
    onChange?.(focusMode, { forceDesktopMode: true })
  }

  function isFocusMode() {
    return focusMode
  }

  function isForceDesktopMode() {
    return forceDesktopMode
  }

  function dispose() {
    focusMode = false
    forceDesktopMode = false
  }

  return {
    renderToggle,
    toggle,
    switchDesktopMode,
    isFocusMode,
    isForceDesktopMode,
    dispose,
  }
}
