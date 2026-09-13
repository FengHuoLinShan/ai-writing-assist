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
import {
  clearDemoCopyIntent,
  consumeEntryMode,
  hasDemoCopyIntent,
} from "./vue/auth/entryMode.js"
import { registerViewLoaders } from "./vue/viewLoaders.js"
import { getThemeController } from "./vue/shell/composables/useTheme.js"
import { notifySmartDedupChanged, registerSmartDedupManager } from "./vue/bridge/index.js"

// 只注册按路由加载的 island import 函数；不会在应用启动或认证门禁期间加载业务模块。
registerViewLoaders()

function isPublicDemoRequest() {
  try { return new URLSearchParams(globalThis.location?.search || "").get("demo") === "1" } catch { return false }
}

function isDemoRpRoute() {
  return String(globalThis.location?.hash || "").replace(/^#/, "").split("/")[0] === "demo-rp"
}

const App = {
  _initialized: false,
  _shell: null,
  _authGate: null,
  _smartDedup: null,
  _unregisterSmartDedup: null,
  _unbindNavigate: null,
  _accountInvalidatedHandler: null,
  _accountStorageHandler: null,
  _accountBoundaryInvalidated: false,
  _authGateLogoutPending: false,
  _demoCopyError: "",
  _mountShell: mountShell,
  _reload: () => globalThis.location.reload(),

  async init() {
    this._bindAccountSecurityEvents()
    if (this._initialized) return this._shell
    getThemeController().initialize()
    this._accountBoundaryInvalidated = false
    this._initialized = true

    try {
      const authConfig = typeof api.auth?.config === "function"
        ? await api.auth.config()
        : { auth_mode: "local", wechat_enabled: false }
      globalThis.accountAuthConfig = authConfig
      if (isPublicDemoRequest() && authConfig.demo?.enabled) {
        return this._startPublicDemo(authConfig)
      }
      globalThis.publicDemoMode = false
      globalThis.publicDemoConfig = null
      globalThis.publicDemoRpMode = false
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
      const copiedProject = await this._copyDemoProjectIfRequested()
      this._restoreProjectState()
      const entryMode = consumeEntryMode()
      if (copiedProject) this._openCopiedDemoProject(copiedProject)
      else this._applyAuthenticatedEntry(entryMode)

      if (!globalThis.publicDemoMode) {
        this._smartDedup = createSmartDedupManager({
          api,
          router,
          toast,
          modal: { showModalHtml, closeModal },
          esc,
          onRenderActions: notifySmartDedupChanged,
          getCurrentProjectId: () => state.currentProjectId,
          getCurrentRouteKey: () => `${state.currentView || ""}:${state.currentSubView || ""}`,
        })
        this._unregisterSmartDedup = registerSmartDedupManager(this._smartDedup)
      }

      // mountShell 先创建 #workspace-content，再初始化现有 hash router。
      this._shell = await this._mountShell()

      const unsubscribe = router.onNavigate?.(() => {
        this._smartDedup?.syncProject(state.currentProjectId)
      })
      this._unbindNavigate = typeof unsubscribe === "function" ? unsubscribe : null

      this._smartDedup?.syncProject(state.currentProjectId)

      if (this._demoCopyError) {
        toast(`已登录，但演示副本暂时无法创建。${this._demoCopyError} 刷新页面可重试。`, "error")
        this._demoCopyError = ""
      } else if (copiedProject) {
        toast({
          created: "已创建演示副本，可以开始修改和生成。",
          existing: "已打开你已有的演示副本。",
          restored: "已恢复并打开你的演示副本。",
        }[copiedProject.status] || "已打开你的演示副本，可以开始修改和生成。", "success")
      }

      console.log("小说结构化创作控制台 v2.0 已启动")
      return this._shell
    } catch (error) {
      this._unbindNavigate?.()
      this._unbindNavigate = null
      this._unregisterSmartDedup?.()
      this._unregisterSmartDedup = null
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
    getThemeController().dispose()
    this._unbindNavigate?.()
    this._unbindNavigate = null
    this._unregisterSmartDedup?.()
    this._unregisterSmartDedup = null
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

  async _startPublicDemo(authConfig) {
    const demo = authConfig.demo
    globalThis.publicDemoMode = true
    globalThis.publicDemoConfig = demo
    globalThis.publicDemoRpMode = isDemoRpRoute() && demo.rp_enabled
    if (!isDemoRpRoute() || !demo.rp_enabled) {
      state.currentProjectId = demo.project_id
      state.currentProject = {
        id: demo.project_id,
        title: demo.title || "演示项目",
        summaryOnly: true,
      }
      if (!globalThis.location.hash || globalThis.location.hash === "#home") {
        globalThis.history.replaceState(null, "", "#today")
      }
      if (isDemoRpRoute() && !demo.rp_enabled) {
        globalThis.history.replaceState(null, "", "#today")
      }
    }
    this._shell = await this._mountShell()
    return this._shell
  },

  async _copyDemoProjectIfRequested() {
    if (!hasDemoCopyIntent()) return null
    try {
      const result = await api.projects.demoCopy()
      const status = String(result?.status || "")
      if (!["created", "existing", "restored"].includes(status)) {
        throw new Error("服务端没有确认演示副本状态")
      }
      const project = result?.project || null
      const projectId = project?.id || result?.project_id || result?.id || null
      if (!projectId) throw new Error("服务端没有返回演示副本")
      clearDemoCopyIntent()
      return {
        id: projectId,
        status,
        title: project?.title || result?.title || "演示副本",
        ...project,
      }
    } catch (error) {
      this._demoCopyError = error?.message || "请稍后重试。"
      return null
    }
  },

  _openCopiedDemoProject(project) {
    state.currentProjectId = project.id
    state.currentProject = project
    globalThis.history.replaceState(null, "", "#today")
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

  _applyAuthenticatedEntry(mode) {
    if (!mode) return
    const hash = mode === "rp" ? "#journeys" : "#today"
    globalThis.history.replaceState(null, "", hash)
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
    const actions = document.createElement("div")
    actions.className = "actions"
    const retry = document.createElement("button")
    retry.type = "button"
    retry.className = "btn btn-primary"
    retry.dataset.action = "retry-app-bootstrap"
    retry.textContent = "重试"
    retry.addEventListener("click", () => {
      retry.disabled = true
      retry.textContent = "正在重试…"
      void this.init().catch(() => {})
    })
    actions.append(retry)
    boundary.append(icon, title, detail, actions)
    host.replaceChildren(boundary)
    retry.focus()
  },
}

document.addEventListener("DOMContentLoaded", () => {
  App.init().catch(() => {})
})

globalThis.App = App
export default App
