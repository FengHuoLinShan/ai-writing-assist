import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import "../stateSlices.js"
import App from "../app.js"
import { storeEntryMode } from "../vue/auth/entryMode.js"

globalThis.projectStorageSummary = globalThis.stateSlices.projectStorageSummary

describe("application bootstrap", () => {
  let unmount

  beforeEach(() => {
    App.dispose()
    localStorage.clear()
    sessionStorage.clear()
    history.replaceState(null, "", "/")
    document.body.innerHTML = '<div id="app"></div>'
    state.currentProjectId = null
    state.currentProject = null
    unmount = vi.fn()
    App._mountShell = vi.fn().mockResolvedValue({ unmount })
    router.onNavigate.mockReturnValue(vi.fn())
  })

  afterEach(() => {
    App.dispose()
    vi.restoreAllMocks()
  })

  it("keeps the stable browser services available", () => {
    expect(globalThis.state).toBeDefined()
    expect(globalThis.esc).toBeDefined()
    expect(globalThis.router).toBeDefined()
    expect(globalThis.api).toBeDefined()
    expect(globalThis.toast).toBeDefined()
    expect(globalThis.showModal).toBeDefined()
    expect(globalThis.App).toBe(App)
  })

  it("restores the safe project summary before mounting the Vue shell", async () => {
    localStorage.setItem("novel_currentProjectId", "p1")
    localStorage.setItem("novel_currentProject", JSON.stringify({
      id: "p1",
      title: "雾港",
      genre: "must-not-restore",
    }))
    App._mountShell.mockImplementation(async () => {
      expect(state.currentProjectId).toBe("p1")
      expect(state.currentProject).toEqual({ id: "p1", title: "雾港", summaryOnly: true })
      return { unmount }
    })

    await App.init()

    expect(App._mountShell).toHaveBeenCalledTimes(1)
    expect(App._initialized).toBe(true)
    await App.init()
    expect(App._mountShell).toHaveBeenCalledTimes(1)
  })

  it("disposes shell and SmartDedup lifecycles", async () => {
    await App.init()
    const disposeDedup = vi.spyOn(App._smartDedup, "dispose")

    App.dispose()

    expect(disposeDedup).toHaveBeenCalledTimes(1)
    expect(unmount).toHaveBeenCalledTimes(1)
    expect(App._initialized).toBe(false)
  })

  it("shows the public entry choice before login without mounting protected routes", async () => {
    api.auth = {
      config: vi.fn().mockResolvedValue({ auth_mode: "public", wechat_enabled: false }),
      me: vi.fn(),
    }
    const unauthorized = new Error("not signed in")
    unauthorized.status = 401
    api.auth.me.mockRejectedValue(unauthorized)

    await App.init()

    expect(App._authGate).not.toBeNull()
    expect(document.querySelectorAll(".entry-card")).toHaveLength(2)
    expect(document.querySelector(".auth-card")).toBeNull()
    expect(App._mountShell).not.toHaveBeenCalled()
    expect(router.initRouter).not.toHaveBeenCalled()
    delete api.auth
  })

  it.each([
    ["author", "#today"],
    ["rp", "#journeys"],
  ])("returns the authenticated account to its selected %s path", async (mode, hash) => {
    api.auth = {
      config: vi.fn().mockResolvedValue({ auth_mode: "public", wechat_enabled: false }),
      me: vi.fn().mockResolvedValue({ id: "account-1", status: "active" }),
    }
    localStorage.setItem("novel_accountId", "account-1")
    storeEntryMode(mode)

    await App.init()

    expect(location.hash).toBe(hash)
    expect(sessionStorage.getItem("nc-entry-mode-after-auth")).toBeNull()
    delete api.auth
  })

  it("renders a safe retry boundary and recovers when shell bootstrap succeeds", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})
    App._mountShell
      .mockRejectedValueOnce(new Error('<img src=x onerror="boom">'))
      .mockResolvedValueOnce({ unmount })

    await expect(App.init()).rejects.toThrow("<img")

    const boundary = document.querySelector('#app [role="alert"]')
    expect(boundary?.textContent).toContain("<img")
    expect(boundary?.querySelector("img")).toBeNull()
    expect(App._initialized).toBe(false)
    const retry = boundary.querySelector('[data-action="retry-app-bootstrap"]')
    expect(document.activeElement).toBe(retry)
    retry.click()
    expect(retry.disabled).toBe(true)
    expect(retry.textContent).toBe("正在重试…")
    await vi.waitFor(() => expect(App._mountShell).toHaveBeenCalledTimes(2))
    expect(App._initialized).toBe(true)
    errorSpy.mockRestore()
  })
})
