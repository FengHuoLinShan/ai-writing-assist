import { afterEach, describe, it, expect, vi, beforeEach } from "vitest"
import App from "../app.js"
import { resetState, clearDocument } from "./helpers.js"
import {
  hasDemoCopyIntent,
  storeDemoCopyIntent,
} from "../vue/auth/entryMode.js"

beforeEach(() => {
  App._unbindAccountSecurityEvents()
  App._accountBoundaryInvalidated = false
  App._reload = vi.fn()
  App._demoCopyError = ""
  resetState({ currentProjectId: "p1", currentView: "world" })
  clearDocument()
  document.body.innerHTML = `
    <div id="app">
      <div id="main-layout">
        <div id="sidebar-context-slot"></div>
        <main id="workspace">
          <div id="workspace-content"></div>
        </main>
      </div>
    </div>
  `
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
  it.each(["created", "existing", "restored"])("consumes the demo copy intent after a %s copy response", async (status) => {
    storeDemoCopyIntent()
    globalThis.api.projects.demoCopy = vi.fn(async () => ({
      status,
      project: { id: `copy-${status}`, title: "我的演示副本" },
    }))

    const copied = await App._copyDemoProjectIfRequested()

    expect(globalThis.api.projects.demoCopy).toHaveBeenCalledTimes(1)
    expect(copied).toMatchObject({ id: `copy-${status}`, title: "我的演示副本" })
    expect(hasDemoCopyIntent()).toBe(false)
  })

  it("keeps the demo copy intent when the post-login copy request fails", async () => {
    storeDemoCopyIntent()
    globalThis.api.projects.demoCopy = vi.fn(async () => { throw new Error("temporary failure") })

    expect(await App._copyDemoProjectIfRequested()).toBeNull()
    expect(hasDemoCopyIntent()).toBe(true)
    expect(App._demoCopyError).toBe("temporary failure")
  })

  it("locks and reloads an old tab when another tab changes the account marker", () => {
    globalThis.currentAccount = { id: "account-old" }
    localStorage.setItem("novel_accountId", "account-new")
    localStorage.setItem("draft_backup_project-old_1", "private")
    localStorage.setItem("world_draft_backup_project-old_page_old", "private world draft")
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
    expect(localStorage.getItem("world_draft_backup_project-old_page_old")).toBeNull()
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

})
