/**
 * 应用启动器。
 *
 * Vue shell 拥有顶部栏、导航、命令栏、主题、快捷键与静态 service hosts；
 * 本文件只保留启动顺序、项目摘要恢复和跨视图 SmartDedup 生命周期。
 */

import { createSmartDedupManager } from "./shared/smartDedup.js"
import { mountShell } from "./vue/shell/mountShell.js"

// 已迁移的 Vue island 在 router 初始化前完成注册。
import "./vue/settingsIslands.js"
import "./vue/projectIsland.js"
import "./vue/ragIsland.js"
import "./vue/worldIsland.js"
import "./vue/outlineIsland.js"
import "./vue/generateIsland.js"
import "./vue/writingIsland.js"
import "./vue/mapIsland.js"

const App = {
  _initialized: false,
  _shell: null,
  _smartDedup: null,
  _unbindNavigate: null,
  _workspace: null,
  _workspaceClickHandler: null,
  _workspaceRenderedHandler: null,
  _mountShell: mountShell,

  async init() {
    if (this._initialized) return this._shell
    this._initialized = true

    try {
      globalThis.installStateGlobalListeners?.()
      this._restoreProjectState()

      this._smartDedup = createSmartDedupManager({
        api,
        router,
        toast,
        modal: { showModalHtml, closeModal },
        esc,
        onRenderActions: () => this._renderGlobalActions(),
        getCurrentProjectId: () => state.currentProjectId,
      })

      // mountShell 先创建 #workspace-content，再初始化现有 hash router。
      this._shell = await this._mountShell()
      this._bindGlobalActions()

      const unsubscribe = router.onNavigate?.(() => {
        this._smartDedup?.syncProject(state.currentProjectId)
        this._renderGlobalActions()
      })
      this._unbindNavigate = typeof unsubscribe === "function" ? unsubscribe : null

      this._smartDedup.syncProject(state.currentProjectId)
      this._renderGlobalActions()

      console.log("小说结构化创作控制台 v2.0 已启动")
      return this._shell
    } catch (error) {
      this._unbindGlobalActions()
      this._unbindNavigate?.()
      this._unbindNavigate = null
      this._smartDedup?.dispose?.()
      this._smartDedup = null
      this._shell?.unmount?.()
      this._shell = null
      globalThis.disposeStateGlobalListeners?.()
      this._initialized = false
      this._showBootstrapError(error)
      throw error
    }
  },

  dispose() {
    this._unbindGlobalActions()
    this._unbindNavigate?.()
    this._unbindNavigate = null
    this._smartDedup?.dispose?.()
    this._smartDedup = null
    this._shell?.unmount?.()
    this._shell = null
    globalThis.disposeStateGlobalListeners?.()
    this._initialized = false
  },

  _bindGlobalActions() {
    this._unbindGlobalActions()
    const workspace = document.getElementById("workspace")
    if (!workspace) return

    this._workspaceClickHandler = (event) => {
      const button = event.target?.closest?.("[data-action]")
      if (!button) return
      const action = button.getAttribute("data-action")
      if (action === "start-smart-dedup" || action === "show-smart-dedup-progress") {
        this._smartDedup?.handleAction(action)
      }
    }
    this._workspaceRenderedHandler = () => this._renderGlobalActions()
    workspace.addEventListener("click", this._workspaceClickHandler)
    workspace.addEventListener("workspace:content-rendered", this._workspaceRenderedHandler)
    this._workspace = workspace
  },

  _unbindGlobalActions() {
    if (this._workspace) {
      this._workspace.removeEventListener("click", this._workspaceClickHandler)
      this._workspace.removeEventListener("workspace:content-rendered", this._workspaceRenderedHandler)
    }
    this._workspace = null
    this._workspaceClickHandler = null
    this._workspaceRenderedHandler = null
  },

  _renderGlobalActions() {
    const mount = document.querySelector('#workspace-content [data-role="smart-dedup-action"]')
    if (!mount) return

    const supportedView = state.currentView === "world" || state.currentView === "outline"
    if (!state.currentProjectId || !supportedView || !this._smartDedup) {
      mount.replaceChildren()
      return
    }

    // SmartDedup 只返回内部生成的静态按钮/进度标记，不含用户或 AI 文本。
    mount.innerHTML = this._smartDedup.renderActionButton(this._smartDedup.getState().progress)
  },

  _projectStorageSummary(project) {
    if (!project || typeof project !== "object") return null
    const summary = {}
    for (const key of ["id", "title", "name"]) {
      if (Object.prototype.hasOwnProperty.call(project, key)) summary[key] = project[key]
    }
    return Object.keys(summary).length > 0 ? summary : null
  },

  _restoreProjectState() {
    try {
      const savedId = localStorage.getItem("novel_currentProjectId")
      if (savedId) state.currentProjectId = savedId

      const savedProject = localStorage.getItem("novel_currentProject")
      if (!savedProject) return
      const parsed = JSON.parse(savedProject)
      const summary = globalThis.projectStorageSummary?.(parsed) || this._projectStorageSummary(parsed)
      if (!summary) return
      if (!state.currentProjectId && summary.id) state.currentProjectId = summary.id
      state.currentProject = { ...summary, summaryOnly: true }
    } catch {}
  },

  _showBootstrapError(error) {
    console.error("Application bootstrap failed:", error)
    const message = `应用启动失败：${error?.message || "未知错误"}`
    if (typeof toast === "function" && document.getElementById("toast-container")) {
      toast(message, "error")
    }

    const host = document.getElementById("workspace-content") || document.getElementById("app")
    if (!host) return
    const boundary = document.createElement("div")
    boundary.className = "empty-state"
    boundary.setAttribute("role", "alert")
    const icon = document.createElement("div")
    icon.className = "empty-icon"
    icon.textContent = "!"
    const title = document.createElement("p")
    title.textContent = "应用启动失败"
    const detail = document.createElement("p")
    detail.textContent = error?.message || "未知错误"
    boundary.append(icon, title, detail)
    host.replaceChildren(boundary)
  },
}

document.addEventListener("DOMContentLoaded", () => {
  App.init().catch(() => {})
})

globalThis.App = App
export default App
