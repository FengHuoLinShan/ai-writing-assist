import { afterEach, describe, it, expect, vi, beforeEach } from "vitest"
import App from "../app.js"
import { createSmartDedupManager } from "../shared/smartDedup.js"
import { resetState, clearDocument } from "./helpers.js"

beforeEach(() => {
  App._unbindAccountSecurityEvents()
  App._accountBoundaryInvalidated = false
  App._reload = vi.fn()
  resetState({ currentProjectId: "p1", currentView: "world" })
  clearDocument()
  document.body.innerHTML = `
    <div id="app">
      <main id="workspace">
        <div id="workspace-content">
          <span data-role="smart-dedup-action"></span>
        </div>
      </main>
    </div>
  `
  App._smartDedup = createSmartDedupManager({
    api,
    router,
    toast,
    modal: { showModalHtml, closeModal },
    esc,
    onRenderActions: () => App._renderGlobalActions(),
    getCurrentProjectId: () => state.currentProjectId,
  })
  App._bindGlobalActions()
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
  App._bindAccountSecurityEvents()
})

afterEach(() => {
  App._unbindAccountSecurityEvents()
  delete globalThis.currentAccount
})

describe("App smart dedup integration", () => {
  it("releases app-lifetime state listeners on dispose", () => {
    const previousDispose = globalThis.disposeStateGlobalListeners
    const disposeStateGlobalListeners = vi.fn()
    globalThis.disposeStateGlobalListeners = disposeStateGlobalListeners
    App._shell = { unmount: vi.fn() }
    App._initialized = true
    try {
      App.dispose()
      expect(disposeStateGlobalListeners).toHaveBeenCalledTimes(1)
      expect(App._initialized).toBe(false)
    } finally {
      if (previousDispose) globalThis.disposeStateGlobalListeners = previousDispose
      else delete globalThis.disposeStateGlobalListeners
    }
  })

  it("locks and reloads an old tab when another tab changes the account marker", () => {
    globalThis.currentAccount = { id: "account-old" }
    localStorage.setItem("novel_accountId", "account-new")
    localStorage.setItem("draft_backup_project-old_1", "private")
    localStorage.setItem("novel_theme", "dark")
    sessionStorage.setItem("workspace-rail:project-old:writing:assistant", "closed")
    App._shell = { unmount: vi.fn() }
    App._initialized = true

    globalThis.dispatchEvent(new StorageEvent("storage", {
      key: "novel_accountId",
      oldValue: "account-old",
      newValue: "account-new",
      storageArea: localStorage,
    }))

    expect(App._shell).toBeNull()
    expect(globalThis.currentAccount).toBeNull()
    expect(state.currentProjectId).toBeNull()
    expect(localStorage.getItem("novel_accountId")).toBe("account-new")
    expect(localStorage.getItem("draft_backup_project-old_1")).toBeNull()
    expect(sessionStorage.getItem("workspace-rail:project-old:writing:assistant")).toBeNull()
    expect(localStorage.getItem("novel_theme")).toBe("dark")
    expect(document.getElementById("app").textContent).toContain("账号状态已变化")
    expect(App._reload).toHaveBeenCalledTimes(1)
  })

  it("does not reload when a storage event confirms the current account marker", () => {
    globalThis.currentAccount = { id: "account-current" }

    globalThis.dispatchEvent(new StorageEvent("storage", {
      key: "novel_accountId",
      oldValue: null,
      newValue: "account-current",
      storageArea: localStorage,
    }))

    expect(App._reload).not.toHaveBeenCalled()
    expect(App._accountBoundaryInvalidated).toBe(false)
  })

  it("renders one local smart dedup button on the world page", () => {
    App._renderGlobalActions()

    const actions = document.querySelector('[data-role="smart-dedup-action"]')
    expect(actions.innerHTML).toContain("智能去重")
    expect(actions.querySelectorAll('[data-action="start-smart-dedup"]')).toHaveLength(1)
  })

  it.each(["project", "writing", "map", "rag", "generate", "settings", "project-settings"])(
    "does not render the smart dedup button on %s",
    (viewName) => {
      state.currentView = viewName

      App._renderGlobalActions()

      expect(document.querySelector('[data-role="smart-dedup-action"]').innerHTML).toBe("")
    },
  )

  it("renders the smart dedup button in an outline-local mount", () => {
    state.currentView = "outline"
    state.currentSubView = "scenes"

    App._renderGlobalActions()

    expect(document.querySelectorAll('[data-action="start-smart-dedup"]')).toHaveLength(1)
  })

  it("delegates start-smart-dedup action to the manager", () => {
    const startScan = vi.spyOn(App._smartDedup, "startScan").mockImplementation(() => {})

    App._renderGlobalActions()
    document.querySelector('[data-action="start-smart-dedup"]').click()

    expect(startScan).toHaveBeenCalledTimes(1)
  })

  it("repaints exactly one action after a local workspace rerender", () => {
    App._renderGlobalActions()
    const content = document.getElementById("workspace-content")
    content.innerHTML = '<span data-role="smart-dedup-action"></span>'

    content.dispatchEvent(new Event("workspace:content-rendered", { bubbles: true }))

    expect(content.querySelectorAll('[data-action="start-smart-dedup"]')).toHaveLength(1)
  })

  it("delegates show-smart-dedup-progress action to the manager", async () => {
    const showProgress = vi.spyOn(App._smartDedup, "showProgress").mockImplementation(() => {})
    api.projects.startSmartDedupScan.mockResolvedValue({ task_id: "scan-1" })
    api.tasks.get.mockResolvedValue({
      task_id: "scan-1",
      task_type: "smart_dedup_scan",
      status: "running",
    })

    await App._smartDedup.startScan()
    App._renderGlobalActions()
    document.querySelector('[data-action="show-smart-dedup-progress"]').click()

    expect(showProgress).toHaveBeenCalledTimes(1)
    App._smartDedup.dispose()
  })
})
