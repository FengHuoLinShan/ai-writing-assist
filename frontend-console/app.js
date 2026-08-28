/**
 * 应用启动器。
 *
 * Vue shell 拥有顶部栏、导航、命令栏、主题、快捷键与静态 service hosts；
 * 本文件只保留启动顺序、项目摘要恢复和跨视图 SmartDedup 生命周期。
 */

import { createSmartDedupManager } from "./shared/smartDedup.js"
import {
  ACCOUNT_INVALIDATED_EVENT,
  ACCOUNT_MARKER_KEY,
  forceAccountSafeReload,
  scopeBrowserStorageToAccount,
} from "./shared/accountStorage.js"
import { mountShell } from "./vue/shell/mountShell.js"
import { mountAuthGate } from "./vue/auth/mountAuthGate.js"
import { registerViewLoaders } from "./vue/viewLoaders.js"

// 只注册按路由加载的 island import 函数；不会在应用启动或认证门禁期间加载业务模块。
registerViewLoaders()

const App = {
  _initialized: false,
  _shell: null,
  _authGate: null,
  _smartDedup: null,
  _unbindNavigate: null,
  _workspace: null,
  _workspaceClickHandler: null,
  _workspaceRenderedHandler: null,
  _accountInvalidatedHandler: null,
  _accountStorageHandler: null,
  _accountBoundaryInvalidated: false,
  _authGateLogoutPending: false,
  _mountShell: mountShell,
  _reload: () => globalThis.location.reload(),

  async init() {
    this._bindAccountSecurityEvents()
    if (this._initialized) return this._shell
    this._accountBoundaryInvalidated = false
    this._initialized = true

    try {
      const authConfig = typeof api.auth?.config === "function"
        ? await api.auth.config()
        : { auth_mode: "local", wechat_enabled: false }
      globalThis.accountAuthConfig = authConfig
      if (authConfig.auth_mode === "public") {
        let account = null
        try { account = await api.auth.me() } catch (error) {
          if (error?.status !== 401) throw error
        }
        if (!account || account.status === "pending_deletion") {
          this._authGate = mountAuthGate({
            config: authConfig,
            account,
            onAuthenticated: (nextAccount) => this._resumeAfterAuthentication(nextAccount),
            onLogout: () => this._logoutFromAuthGate(),
          })
          return this._authGate
        }
        this._scopeBrowserState(account.id)
        globalThis.currentAccount = account
      }
      this._restoreProjectState()

      this._smartDedup = createSmartDedupManager({
        api,
        router,
        toast,
        modal: { showModalHtml, closeModal },
        esc,
        onRenderActions: () => this._renderGlobalActions(),
        getCurrentProjectId: () => state.currentProjectId,
        getCurrentRouteKey: () => `${state.currentView || ""}:${state.currentSubView || ""}`,
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
      this._initialized = false
      if (!this._accountBoundaryInvalidated) this._showBootstrapError(error)
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
    this._authGate?.unmount?.()
    this._authGate = null
    this._unbindAccountSecurityEvents()
    this._initialized = false
  },

  async _resumeAfterAuthentication(account) {
    this._scopeBrowserState(account?.id)
    globalThis.currentAccount = account
    this._authGate?.unmount?.()
    this._authGate = null
    this._initialized = false
    await this.init()
  },

  _scopeBrowserState(accountId) {
    if (scopeBrowserStorageToAccount(accountId)) api.clearCache()
  },

  async _logoutFromAuthGate() {
    if (this._authGateLogoutPending) return
    this._authGateLogoutPending = true
    try {
      await api.auth?.logout?.()
    } finally {
      this._authGateLogoutPending = false
      api.clearCache?.()
      forceAccountSafeReload({
        reason: "pending-deletion-logout",
        reload: this._reload,
      })
    }
  },

  _bindAccountSecurityEvents() {
    if (this._accountInvalidatedHandler || typeof globalThis.addEventListener !== "function") return
    this._accountInvalidatedHandler = (event) => this._enterSafeAccountBoundary(event)
    this._accountStorageHandler = (event) => {
      if (event?.key !== ACCOUNT_MARKER_KEY) return
      const currentAccountId = globalThis.currentAccount?.id
        ? String(globalThis.currentAccount.id)
        : null
      if (currentAccountId && event.newValue === currentAccountId) return
      forceAccountSafeReload({
        reason: "account-marker-changed",
        preserveAccountMarker: true,
        reload: this._reload,
      })
    }
    globalThis.addEventListener(ACCOUNT_INVALIDATED_EVENT, this._accountInvalidatedHandler)
    globalThis.addEventListener("storage", this._accountStorageHandler)
  },

  _unbindAccountSecurityEvents() {
    if (typeof globalThis.removeEventListener === "function") {
      if (this._accountInvalidatedHandler) {
        globalThis.removeEventListener(ACCOUNT_INVALIDATED_EVENT, this._accountInvalidatedHandler)
      }
      if (this._accountStorageHandler) {
        globalThis.removeEventListener("storage", this._accountStorageHandler)
      }
    }
    this._accountInvalidatedHandler = null
    this._accountStorageHandler = null
  },

  _enterSafeAccountBoundary(event) {
    event?.preventDefault?.()
    if (this._accountBoundaryInvalidated) return
    this._accountBoundaryInvalidated = true
    const reload = this._reload

    try {
      try { this.dispose() } catch {}
      globalThis.currentAccount = null
      try {
        state.currentProjectId = null
        state.currentProject = null
        state.projects = []
        state.selectedItem = null
        state.viewStates = {}
      } catch {}

      const root = document.querySelector("#app")
      if (root) {
        const boundary = document.createElement("main")
        boundary.className = "empty-state"
        boundary.setAttribute("role", "status")
        const title = document.createElement("p")
        title.textContent = "账号状态已变化"
        const detail = document.createElement("p")
        detail.textContent = "正在安全刷新，请稍候。"
        boundary.append(title, detail)
        root.replaceChildren(boundary)
      }
    } finally {
      reload()
    }
  },

  _bindGlobalActions() {
    this._unbindGlobalActions()
    const workspace = document.getElementById("workspace")
    if (!workspace) return
    const clickRoot = document.getElementById("main-layout") || workspace

    this._workspaceClickHandler = (event) => {
      const button = event.target?.closest?.("[data-action]")
      if (!button) return
      const action = button.getAttribute("data-action")
      if (action === "start-smart-dedup" || action === "show-smart-dedup-progress") {
        this._smartDedup?.handleAction(action)
      }
    }
    this._workspaceRenderedHandler = () => this._renderGlobalActions()
    clickRoot.addEventListener("click", this._workspaceClickHandler)
    workspace.addEventListener("workspace:content-rendered", this._workspaceRenderedHandler)
    this._workspace = workspace
    this._globalActionRoot = clickRoot
  },

  _unbindGlobalActions() {
    if (this._workspace) {
      this._workspace.removeEventListener("workspace:content-rendered", this._workspaceRenderedHandler)
    }
    this._globalActionRoot?.removeEventListener("click", this._workspaceClickHandler)
    this._workspace = null
    this._globalActionRoot = null
    this._workspaceClickHandler = null
    this._workspaceRenderedHandler = null
  },

  _renderGlobalActions() {
    const mounts = document.querySelectorAll('[data-role="smart-dedup-action"]')
    if (!mounts.length) return

    const supportedView = state.currentView === "world" || state.currentView === "outline"
    if (!state.currentProjectId || !supportedView || !this._smartDedup) {
      mounts.forEach((mount) => mount.replaceChildren())
      return
    }

    // SmartDedup 只返回内部生成的静态按钮/进度标记，不含用户或 AI 文本。
    const html = this._smartDedup.renderActionButton(this._smartDedup.getState().progress)
    mounts.forEach((mount) => { mount.innerHTML = html })
  },

  _restoreProjectState() {
    try {
      const savedId = localStorage.getItem("novel_currentProjectId")
      if (savedId) state.currentProjectId = savedId

      const savedProject = localStorage.getItem("novel_currentProject")
      if (!savedProject) return
      const parsed = JSON.parse(savedProject)
      const summary = globalThis.projectStorageSummary(parsed)
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
