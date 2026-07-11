/**
 * Router regression tests
 */
import { describe, it, expect, vi, beforeEach } from "vitest"

import "../router.js"

beforeEach(() => {
  vi.clearAllMocks()
  document.body.replaceChildren()
  localStorage.clear()
  window.history.replaceState(null, "", "#")
  state.currentProjectId = null
  state.currentProject = null
  state.currentView = "project"
  state.currentSubView = null
  state.selectedItem = null
  state.selectedItems = []
})

function addWorkspace() {
  const content = document.createElement("div")
  content.id = "workspace-content"
  document.body.append(content)
  return content
}

function registerBasicView(name) {
  window.router.registerView(name, {
    async render() {
      return `<p>${name}:${state.currentSubView || ""}</p>`
    },
  })
}

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

  it("keeps a writing view's module state alive while its DOM is cached", async () => {
    const content = addWorkspace()
    const onDeactivate = vi.fn()
    const onLeave = vi.fn()
    const onActivate = vi.fn()
    const onEnter = vi.fn()

    window.router.registerView("writing", {
      onEnter,
      onDeactivate,
      onLeave,
      onActivate,
      async render() {
        return '<p id="writing-state">章节树仍在</p>'
      },
    })
    window.router.registerView("world", { async render() { return "<p>世界</p>" } })

    state.currentProjectId = "writing-lifecycle-p1"
    state.currentProject = { id: "writing-lifecycle-p1", title: "项目一" }
    state.currentView = "writing"
    state.currentSubView = null
    await window.router.renderCurrentView()

    await window.router.navigate("world", null, false)
    expect(onDeactivate).toHaveBeenCalledTimes(1)
    expect(onLeave).not.toHaveBeenCalled()

    await window.router.navigate("writing", null, false)
    expect(onActivate).toHaveBeenCalledTimes(1)
    expect(onEnter).toHaveBeenCalledTimes(1)
    expect(content.querySelector("#writing-state")?.textContent).toBe("章节树仍在")
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

describe("route guard and normalization", () => {
  it("redirects active project-scoped navigation to projects when no project is selected", async () => {
    addWorkspace()
    registerBasicView("project")
    registerBasicView("writing")

    await window.router.navigate("writing")

    expect(state.currentView).toBe("project")
    expect(state.currentSubView).toBeNull()
    expect(window.location.hash).toBe("#project")
    expect(window.location.hash).not.toContain("workbench")
    expect(toast).toHaveBeenCalledTimes(1)
    expect(toast).toHaveBeenCalledWith("请先选择项目后再进入该页面", "warning")
  })

  it("keeps active project-scoped navigation inside the selected workbench", async () => {
    addWorkspace()
    registerBasicView("writing")
    state.currentProjectId = "p1"
    state.currentProject = { id: "p1", title: "项目一" }

    await window.router.navigate("writing")

    expect(state.currentView).toBe("writing")
    expect(state.currentSubView).toBeNull()
    expect(window.location.hash).toBe("#workbench/p1/writing")
    expect(toast).not.toHaveBeenCalled()
  })

  it("normalizes illegal fixed subviews to the route default on init", async () => {
    addWorkspace()
    registerBasicView("world")
    api.projects.get.mockResolvedValue({ id: "p1", title: "项目一" })
    window.location.hash = "#workbench/p1/world/not-real"

    await window.router.initRouter()

    expect(state.currentProjectId).toBe("p1")
    expect(state.currentView).toBe("world")
    expect(state.currentSubView).toBe("objects")
    expect(window.location.hash).toBe("#workbench/p1/world/objects")
  })

  it("redirects legacy scene routes into the outline scene workbench", async () => {
    addWorkspace()
    registerBasicView("outline")
    api.projects.get.mockResolvedValue({ id: "p1", title: "项目一" })
    window.location.hash = "#workbench/p1/scene/s1"

    await window.router.initRouter()

    expect(state.currentView).toBe("outline")
    expect(state.currentSubView).toBe("scenes")
    expect(window.location.hash).toBe("#workbench/p1/outline/scenes?scene_id=s1")
    expect(window.router.getCurrentQuery().get("scene_id")).toBe("s1")
  })

  it("redirects legacy context routes without a project to projects", async () => {
    addWorkspace()
    registerBasicView("project")
    registerBasicView("generate")
    window.location.hash = "#context"

    await window.router.initRouter()

    expect(state.currentView).toBe("project")
    expect(state.currentSubView).toBeNull()
    expect(window.location.hash).toBe("#project")
    expect(window.router.getCurrentQuery().get("tab")).toBeNull()
    expect(toast).not.toHaveBeenCalled()
  })

  it("redirects legacy workbench context routes to the generate task tab", async () => {
    addWorkspace()
    registerBasicView("generate")
    api.projects.get.mockResolvedValue({ id: "p1", title: "项目一" })
    window.location.hash = "#workbench/p1/context"
    await window.router.initRouter()

    expect(state.currentView).toBe("generate")
    expect(state.currentSubView).toBeNull()
    expect(window.location.hash).toBe("#workbench/p1/generate?tab=task")
    expect(window.router.getCurrentQuery().get("tab")).toBe("task")
  })

  it("normalizes llm compatibility routes by project scope", async () => {
    addWorkspace()
    registerBasicView("settings")
    registerBasicView("project-settings")
    window.location.hash = "#llm"

    await window.router.initRouter()

    expect(state.currentView).toBe("settings")
    expect(state.currentSubView).toBeNull()
    expect(window.location.hash).toBe("#settings")

    api.projects.get.mockResolvedValue({ id: "p1", title: "项目一" })
    window.location.hash = "#workbench/p1/llm"
    await window.router.initRouter()

    expect(state.currentProjectId).toBe("p1")
    expect(state.currentView).toBe("project-settings")
    expect(state.currentSubView).toBeNull()
    expect(window.location.hash).toBe("#workbench/p1/project-settings")
  })

  it("keeps world candidates as a valid guarded subview", async () => {
    addWorkspace()
    registerBasicView("world")
    api.projects.get.mockResolvedValue({ id: "p1", title: "项目一" })
    window.location.hash = "#workbench/p1/world/candidates"

    await window.router.initRouter()

    expect(state.currentView).toBe("world")
    expect(state.currentSubView).toBe("candidates")
    expect(window.location.hash).toBe("#workbench/p1/world/candidates")
  })

  it("normalizes restored project-scoped hashes into the current workbench", async () => {
    addWorkspace()
    registerBasicView("writing")
    state.currentProjectId = "p1"
    state.currentProject = { id: "p1", title: "项目一" }
    window.location.hash = "#writing"

    await window.router.initRouter()

    expect(state.currentView).toBe("writing")
    expect(state.currentSubView).toBeNull()
    expect(window.location.hash).toBe("#workbench/p1/writing")
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

  it("re-fetches full project metadata after restoring a legacy project object summary", async () => {
    const { default: App } = await import("../app.js")
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.append(content)

    localStorage.clear()
    state.currentProjectId = null
    state.currentProject = null
    window.location.hash = "#workbench/p1/writing"
    localStorage.setItem("novel_currentProjectId", "p1")
    localStorage.setItem("novel_currentProject", JSON.stringify({
      id: "p1",
      title: "Stored",
      name: "Stored Name",
      genre: "leaky genre",
      tone: "leaky tone",
      current_stage: "writing",
      target_length: "epic",
      updated_at: "2026-07-07T00:00:00Z",
    }))
    api.projects.get.mockResolvedValue({
      id: "p1",
      title: "Fetched",
      genre: "fantasy",
      tone: "warm",
    })
    window.router.registerView("writing", { async render() { return "<p>写作台</p>" } })

    App._restoreProjectState()

    expect(state.currentProject).toEqual({
      id: "p1",
      title: "Stored",
      name: "Stored Name",
      summaryOnly: true,
    })

    await window.router.initRouter()

    expect(api.projects.get).toHaveBeenCalledWith("p1")
    expect(state.currentProject).toEqual({
      id: "p1",
      title: "Fetched",
      genre: "fantasy",
      tone: "warm",
    })
  })
})

describe("scene workbench navigation compatibility", () => {
  it("normalizes programmatic scene navigation into the outline scenes tab", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.append(content)

    window.router.registerView("outline", {
      async render() { return `<p>${state.currentSubView}</p>` },
    })

    state.currentProjectId = "p1"

    await window.router.navigate("scene", "s1", false)

    expect(state.currentView).toBe("outline")
    expect(state.currentSubView).toBe("scenes")
    expect(window.router.getCurrentQuery().get("scene_id")).toBe("s1")
    expect(content.textContent).toContain("scenes")
  })
})
