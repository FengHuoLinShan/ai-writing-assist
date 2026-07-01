/**
 * Router regression tests
 */
import { describe, it, expect, vi, beforeEach } from "vitest"

import "../router.js"

beforeEach(() => {
  vi.clearAllMocks()
  document.body.replaceChildren()
  window.location.hash = ""
})

describe("renderCurrentView error handling", () => {
  it("escapes renderer error messages in the fallback UI", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.append(content)

    const maliciousMessage = "<img src=x onerror=alert('router')>"
    const evilView = {
      async render() {
        throw new Error(maliciousMessage)
      },
    }

    state.currentView = "evil-test-view"
    window.router.registerView("evil-test-view", evilView)

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})
    await window.router.renderCurrentView()
    errorSpy.mockRestore()

    expect(content.querySelector("img")).toBeNull()
    expect(content.textContent).toContain(maliciousMessage)
  })

  it("shows a visible warning when project metadata cannot be loaded", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.append(content)

    window.router.registerView("writing", { async render() { return "<p>写作台</p>" } })
    api.projects.get.mockRejectedValue(new Error("offline"))
    window.location.hash = "#workbench/p1/writing"

    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})
    await window.router.initRouter()
    warnSpy.mockRestore()

    expect(toast).toHaveBeenCalledWith("项目信息加载失败，可稍后重试", "warning")
    expect(state.currentProject).toBeNull()
  })
})

describe("subview memory", () => {
  it("does not restore the world/map compatibility entry from primary world navigation", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.append(content)

    window.router.registerView("world", { async render() { return "" } })
    window.router.registerView("map", { async render() { return "" } })

    state.currentView = "world"
    state.currentSubView = "objects"

    await window.router.navigate("world", "map", false)
    await window.router.navigate("map", null, false)

    expect(window.router.getLastSubView("world")).toBe("objects")
  })
})
