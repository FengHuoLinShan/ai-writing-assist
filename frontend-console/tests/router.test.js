/**
 * Router regression tests
 */
import { describe, it, expect, vi, beforeEach } from "vitest"

import "../router.js"
import sceneWorkbenchView from "../views/sceneWorkbenchView.js"

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

  it("does not reuse keep-alive writing DOM across projects", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.append(content)

    const onEnter = vi.fn()
    const onActivate = vi.fn()
    window.router.registerView("writing", {
      onEnter,
      onActivate,
      onDeactivate: vi.fn(),
      onLeave: vi.fn(),
      async render() {
        return `<p id="writing-project">${state.currentProjectId}</p>`
      },
    })
    window.router.registerView("project", { async render() { return "<p>项目</p>" } })

    state.currentProjectId = "p1"
    state.currentView = "writing"
    state.currentSubView = null
    await window.router.renderCurrentView()
    expect(document.getElementById("writing-project").textContent).toBe("p1")
    const enterCountAfterProjectOne = onEnter.mock.calls.length
    const activateCountAfterProjectOne = onActivate.mock.calls.length

    await window.router.navigate("project", null, false)

    state.currentProjectId = "p2"
    await window.router.navigate("writing", null, false)

    expect(document.getElementById("writing-project").textContent).toBe("p2")
    expect(onEnter).toHaveBeenCalledTimes(enterCountAfterProjectOne + 1)
    expect(onActivate).toHaveBeenCalledTimes(activateCountAfterProjectOne)
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

describe("refresh forces project sync", () => {
  it("re-fetches current project metadata even when project is unchanged", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.append(content)

    window.router.registerView("writing", { async render() { return "<p>写作台</p>" } })

    state.currentProjectId = "p1"
    state.currentProject = { id: "p1", title: "Old" }
    state.currentView = "writing"
    state.currentSubView = null

    api.projects.get.mockResolvedValue({ id: "p1", title: "New" })

    await window.router.refresh()

    expect(api.projects.get).toHaveBeenCalledWith("p1")
    expect(state.currentProject.title).toBe("New")
  })
})

describe("scene workbench navigation lifecycle", () => {
  it("leaving scene workbench does not clear the target route subview", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.append(content)

    window.router.registerView("scene", {
      onLeave: () => sceneWorkbenchView.onLeave(),
      async render() { return "<p>Scene 工作台</p>" },
    })
    window.router.registerView("outline", {
      async render() { return `<p>${state.currentSubView}</p>` },
    })

    state.currentProjectId = "p1"

    await window.router.navigate("scene", "s1", false)
    await window.router.navigate("outline", "scenes", false)

    expect(state.currentView).toBe("outline")
    expect(state.currentSubView).toBe("scenes")
    expect(content.textContent).toContain("scenes")
  })
})
