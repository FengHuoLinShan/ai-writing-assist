/**
 * Router regression tests
 */
import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest"

import "../router.js"

beforeEach(() => {
  vi.clearAllMocks()
  api.projects.get.mockReset()
  closeModal.mockReset()
  closeModal.mockReturnValue(true)
  document.body.replaceChildren()
  localStorage.clear()
  window.history.replaceState(null, "", "#")
  window.appState = state
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
  it("keeps the unavailable-route fallback's established visual contract", async () => {
    const content = addWorkspace()
    window.appState.currentView = "unavailable-fallback-control"

    await window.router.renderCurrentView()

    const fallback = content.querySelector(".empty-state")
    expect(fallback).not.toBeNull()
    const [label, copy] = fallback.querySelectorAll("p")
    expect(fallback.querySelector(".empty-icon")?.textContent).toBe("☐")
    expect(label?.textContent).toBe("unavailable-fallback-control 页面")
    expect(copy?.textContent).toBe("此模块正在开发中，敬请期待")
    expect(copy?.style.color).toBe("var(--text-dim)")
    expect(copy?.style.fontSize).toBe("12px")
  })

  it("renders an unavailable currentView label as literal text", async () => {
    const content = addWorkspace()
    const payload = '<img data-router-fallback-payload src="x" onerror="alert(1)">'
    window.appState.currentView = payload

    await window.router.renderCurrentView()

    expect(content.querySelector("[data-router-fallback-payload]")).toBeNull()
    expect(content.textContent).toContain(`${payload} 页面`)
  })

  it("keeps an already registered renderer ahead of its lazy loader", async () => {
    const content = addWorkspace()
    const loader = vi.fn()
    window.router.registerViewLoader("eager-renderer-wins", loader)
    window.router.registerView("eager-renderer-wins", {
      async render() { return '<p id="eager-wins">ready</p>' },
    })
    state.currentView = "eager-renderer-wins"

    await window.router.renderCurrentView()

    expect(loader).not.toHaveBeenCalled()
    expect(content.querySelector("#eager-wins")?.textContent).toBe("ready")
  })

  it("rejects prototype keys from dynamic view registration", async () => {
    addWorkspace()
    const maliciousRenderer = {
      render: vi.fn(async () => '<p id="prototype-route">unsafe</p>'),
    }

    window.router.registerView("__proto__", maliciousRenderer)
    window.router.registerViewLoader("constructor", vi.fn())
    state.currentView = "__proto__"

    await window.router.renderCurrentView()

    expect(maliciousRenderer.render).not.toHaveBeenCalled()
    expect(document.getElementById("prototype-route")).toBeNull()
  })

  it("deduplicates a pending route loader", async () => {
    const content = addWorkspace()
    let resolveLoader
    const loader = vi.fn(() => new Promise((resolve) => { resolveLoader = resolve }))
    window.router.registerViewLoader("dedupe-loader-test", loader)
    state.currentView = "dedupe-loader-test"

    const first = window.router.renderCurrentView()
    await vi.waitFor(() => expect(loader).toHaveBeenCalledTimes(1))
    const second = window.router.renderCurrentView()
    window.router.registerView("dedupe-loader-test", {
      async render() { return '<p id="dedupe-loaded">loaded</p>' },
    })
    resolveLoader()

    await expect(first).resolves.toBe(false)
    await expect(second).resolves.toBe(true)
    expect(loader).toHaveBeenCalledTimes(1)
    expect(content.querySelector("#dedupe-loaded")).not.toBeNull()
  })

  it("does not mount a late loader after navigating from A to B", async () => {
    const content = addWorkspace()
    let resolveA
    const renderA = vi.fn(async () => '<p id="late-a">A</p>')
    window.router.registerViewLoader("late-loader-a", () => new Promise((resolve) => {
      resolveA = () => {
        window.router.registerView("late-loader-a", { render: renderA })
        resolve()
      }
    }))
    window.router.registerViewLoader("late-loader-b", async () => {
      window.router.registerView("late-loader-b", {
        async render() { return '<p id="late-b">B</p>' },
      })
    })

    state.currentView = "late-loader-a"
    const loadingA = window.router.renderCurrentView()
    await vi.waitFor(() => expect(resolveA).toBeTypeOf("function"))
    state.currentView = "late-loader-b"
    await window.router.renderCurrentView()
    resolveA()

    await expect(loadingA).resolves.toBe(false)
    expect(renderA).not.toHaveBeenCalled()
    expect(content.querySelector("#late-b")).not.toBeNull()
    expect(content.querySelector("#late-a")).toBeNull()
  })

  it("shows a safe retry for a rejected loader and retries from a cleared pending slot", async () => {
    const content = addWorkspace()
    const secret = '<img src=x onerror=alert("loader")>'
    const loader = vi.fn()
      .mockRejectedValueOnce(new Error(secret))
      .mockImplementationOnce(async () => {
        window.router.registerView("retry-loader-test", {
          async render() { return '<p id="retry-loaded">recovered</p>' },
        })
      })
    window.router.registerViewLoader("retry-loader-test", loader)
    state.currentView = "retry-loader-test"
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})

    await window.router.renderCurrentView()

    expect(content.querySelector('[data-action="retry-route-render"]')).not.toBeNull()
    expect(content.textContent).toContain("页面加载失败")
    expect(content.textContent).not.toContain(secret)
    expect(content.textContent).not.toContain("此模块正在开发中")
    content.querySelector('[data-action="retry-route-render"]').click()
    await vi.waitFor(() => expect(content.querySelector("#retry-loaded")).not.toBeNull())
    errorSpy.mockRestore()

    expect(loader).toHaveBeenCalledTimes(2)
  })

  it("offers a guarded application refresh only in the route load failure state", async () => {
    const content = addWorkspace()
    window.router.registerViewLoader("refresh-failure-test", async () => {
      throw new Error("offline")
    })
    state.currentView = "refresh-failure-test"
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})
    const confirmSpy = vi.fn(() => false)
    vi.stubGlobal("confirm", confirmSpy)
    const reloadSpy = vi.spyOn(globalThis.location, "reload").mockImplementation(() => {})

    await window.router.renderCurrentView()

    const refresh = content.querySelector('[data-action="refresh-application"]')
    expect(refresh).not.toBeNull()
    expect(content.textContent).toContain("未保存的输入可能会丢失")
    refresh.click()
    expect(confirmSpy).toHaveBeenCalledOnce()
    expect(reloadSpy).not.toHaveBeenCalled()

    confirmSpy.mockReturnValue(true)
    refresh.click()
    expect(reloadSpy).toHaveBeenCalledOnce()
    errorSpy.mockRestore()
    vi.unstubAllGlobals()
    reloadSpy.mockRestore()
  })

  it("fails a configured loader that resolves without self-registering", async () => {
    const content = addWorkspace()
    window.router.registerViewLoader("unregistered-loader-test", async () => {})
    state.currentView = "unregistered-loader-test"
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})

    await window.router.renderCurrentView()
    errorSpy.mockRestore()

    expect(content.textContent).toContain("页面加载失败")
    expect(content.textContent).not.toContain("此模块正在开发中")
  })

  it("ignores a loader that resolves after its workspace host is detached", async () => {
    const content = addWorkspace()
    let resolveLoader
    const render = vi.fn(async () => '<p id="detached-late">late</p>')
    window.router.registerViewLoader("detached-loader-test", () => new Promise((resolve) => {
      resolveLoader = () => {
        window.router.registerView("detached-loader-test", { render })
        resolve()
      }
    }))
    state.currentView = "detached-loader-test"

    const rendering = window.router.renderCurrentView()
    await vi.waitFor(() => expect(resolveLoader).toBeTypeOf("function"))
    content.remove()
    resolveLoader()

    await expect(rendering).resolves.toBe(false)
    expect(render).not.toHaveBeenCalled()
  })

  it("keeps the mounted lifecycle cleanup exact after a lazy route loads", async () => {
    const content = addWorkspace()
    const onLeave = vi.fn()
    window.router.registerViewLoader("lazy-lifecycle-a", async () => {
      window.router.registerView("lazy-lifecycle-a", {
        onLeave,
        async render() { return '<p id="lazy-lifecycle-a">A</p>' },
      })
    })
    window.router.registerView("lazy-lifecycle-b", {
      async render() { return '<p id="lazy-lifecycle-b">B</p>' },
    })
    state.currentView = "lazy-lifecycle-a"
    await window.router.renderCurrentView()
    state.currentView = "lazy-lifecycle-b"

    await window.router.renderCurrentView()

    expect(onLeave).toHaveBeenCalledTimes(1)
    expect(content.querySelector("#lazy-lifecycle-b")).not.toBeNull()
  })

  it("normalizes the legacy llm route before invoking the settings loader", async () => {
    const content = addWorkspace()
    const settingsLoader = vi.fn(async () => {
      window.router.registerView("settings", {
        async render() { return '<p id="lazy-settings">settings</p>' },
      })
    })
    window.router.registerViewLoader("settings", settingsLoader)
    window.history.replaceState(null, "", "#llm")

    await window.router.initRouter()

    expect(state.currentView).toBe("settings")
    expect(settingsLoader).toHaveBeenCalledTimes(1)
    expect(content.querySelector("#lazy-settings")).not.toBeNull()
  })

  it("stamps route markers for view-scoped presentation without changing rendered markup", async () => {
    const content = addWorkspace()
    registerBasicView("world")
    state.currentView = "world"
    state.currentSubView = "bible"

    await window.router.renderCurrentView()

    expect(content.dataset.workspaceView).toBe("world")
    expect(content.dataset.workspaceSubview).toBe("bible")
    expect(content.innerHTML).toContain("world:bible")
  })

  it("shows an accessible route-host skeleton while a fresh view enters", async () => {
    const content = addWorkspace()
    let releaseEnter
    window.router.registerView("slow-loading-test", {
      onEnter: () => new Promise((resolve) => { releaseEnter = resolve }),
      async render() { return '<p id="loaded-route">完成</p>' },
    })
    state.currentView = "slow-loading-test"

    const rendering = window.router.renderCurrentView()
    await vi.waitFor(() => expect(releaseEnter).toBeTypeOf("function"))

    const status = content.querySelector(".loading-skeleton")
    expect(status?.getAttribute("role")).toBe("status")
    expect(status?.getAttribute("aria-live")).toBe("polite")
    expect(status?.getAttribute("aria-busy")).toBe("true")
    expect(status?.querySelector(".sr-only")?.textContent).toBe("工作区加载中...")
    expect(status?.querySelectorAll('.skeleton[aria-hidden="true"]')).toHaveLength(4)

    releaseEnter()
    await rendering
    expect(content.querySelector("#loaded-route")?.textContent).toBe("完成")
  })

  it("does not let an older async render overwrite the current route", async () => {
    const content = addWorkspace()
    let resolveOld
    const oldRendered = vi.fn()
    window.router.registerView("async-old-view", {
      render: () => new Promise((resolve) => { resolveOld = resolve }),
      onRendered: oldRendered,
    })
    window.router.registerView("async-new-view", {
      async render() { return '<p id="new-route">new</p>' },
    })

    state.currentView = "async-old-view"
    const oldRender = window.router.renderCurrentView()
    await vi.waitFor(() => expect(resolveOld).toBeTypeOf("function"))
    state.currentView = "async-new-view"
    await window.router.renderCurrentView()
    resolveOld('<p id="old-route">old</p>')

    await expect(oldRender).resolves.toBe(false)
    expect(content.querySelector("#new-route")).not.toBeNull()
    expect(content.querySelector("#old-route")).toBeNull()
    expect(oldRendered).not.toHaveBeenCalled()
  })

  it("runs onRendered only after the fresh DOM has been committed", async () => {
    const content = addWorkspace()
    const order = []
    window.router.registerView("render-lifecycle-test", {
      async render() {
        order.push("render")
        return '<button id="rendered-action">操作</button>'
      },
      onRendered() {
        order.push(document.getElementById("rendered-action") ? "bound" : "missing")
      },
    })
    state.currentView = "render-lifecycle-test"

    await window.router.renderCurrentView()

    expect(order).toEqual(["render", "bound"])
    expect(content.querySelector("#rendered-action")).not.toBeNull()
  })

  it("does not expose renderer diagnostics in the fallback UI", async () => {
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
    expect(content.textContent).not.toContain(maliciousMessage)
    expect(content.textContent).toContain("你的项目内容没有受到影响")
  })

  it("shows a visible warning when project metadata cannot be loaded", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.append(content)

    window.router.registerView("writing", { async render() { return "<p>写作台</p>" } })
    api.projects.get.mockRejectedValue(new Error("offline"))
    window.history.replaceState(null, "", "#workbench/p1/writing")

    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})
    await window.router.initRouter()
    warnSpy.mockRestore()

    expect(toast).toHaveBeenCalledWith("项目信息加载失败，可稍后重试", "warning")
    expect(state.currentProject).toBeNull()
  })

  it("removes the old project before awaiting cross-project metadata", async () => {
    const content = addWorkspace()
    let resolveProject
    const onLeave = vi.fn()
    window.router.registerView("world", {
      onLeave,
      async render() {
        return `<p data-project-copy="${state.currentProjectId}">${state.currentProjectId}</p>`
      },
    })

    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "world"
    state.currentSubView = "objects"
    await window.router.renderCurrentView()
    expect(content.textContent).toContain("project-a")

    api.projects.get.mockImplementation(() => new Promise((resolve) => {
      resolveProject = resolve
    }))
    window.history.replaceState(null, "", "#workbench/project-b/world/objects")
    const switching = window.router.initRouter()
    await vi.waitFor(() => expect(resolveProject).toBeTypeOf("function"))

    expect(onLeave).toHaveBeenCalledTimes(1)
    expect(content.textContent).not.toContain("project-a")
    expect(content.querySelector(".loading-skeleton")).not.toBeNull()
    expect(content.dataset.workspaceView).toBe("loading")
    expect(content.dataset.workspaceSubview).toBe("project-transition")

    resolveProject({ id: "project-b", title: "项目 B" })
    await switching

    expect(content.textContent).toContain("project-b")
    expect(content.textContent).not.toContain("project-a")
  })

  it("runs onLeave against the mounted project when programmatic state already points at the target", async () => {
    const content = addWorkspace()
    const leaveSnapshots = []
    window.router.registerView("writing", {
      onLeave() {
        leaveSnapshots.push({
          projectId: state.currentProjectId,
          project: state.currentProject?.id,
        })
      },
      async render() {
        return `<p>${state.currentProjectId}</p>`
      },
    })
    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "writing"
    await window.router.renderCurrentView()

    state.currentProjectId = "project-b"
    state.currentProject = { id: "project-b", title: "项目 B 的预选摘要" }
    api.projects.get.mockResolvedValue({ id: "project-b", title: "项目 B" })

    await window.router.navigate("writing", null, false)

    expect(leaveSnapshots).toEqual([{
      projectId: "project-a",
      project: "project-a",
    }])
    expect(state.currentProjectId).toBe("project-b")
    expect(state.currentProject).toEqual({ id: "project-b", title: "项目 B" })
    expect(content.textContent).toContain("project-b")
  })

  it.each([403, 404, 422])(
    "shows an inaccessible project recovery page for status %i without rendering the target workbench",
    async (status) => {
    const content = addWorkspace()
    const render = vi.fn(async () => (
      `<p data-project-copy="${state.currentProjectId}">${state.currentProjectId}</p>`
    ))
    const onLeave = vi.fn()
    window.router.registerView("writing", { render, onLeave })

    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "writing"
    await window.router.renderCurrentView()
    expect(render).toHaveBeenCalledTimes(1)

    const error = new Error("not found")
    error.status = status
    api.projects.get.mockRejectedValue(error)
    window.history.replaceState(null, "", "#workbench/project-b/writing")
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})
    await window.router.initRouter()
    warnSpy.mockRestore()

    expect(onLeave).toHaveBeenCalledTimes(1)
    expect(render).toHaveBeenCalledTimes(1)
    expect(content.textContent).not.toContain("project-a")
    expect(content.textContent).toContain("无法打开这部作品")
    expect(content.textContent).toContain("作品不存在，或你没有访问权限。")
    expect(content.querySelector('[data-action="retry-project-route"]')).toBeNull()
    expect(content.querySelector('[data-action="return-project-list"]')).not.toBeNull()
    expect(state.currentProjectId).toBeNull()
    expect(state.currentProject).toBeNull()
    expect(toast).not.toHaveBeenCalledWith(
      "项目信息加载失败，可稍后重试",
      "warning",
    )
    },
  )

  it("retries a temporary project metadata failure without restoring old project content", async () => {
    const content = addWorkspace()
    window.router.registerView("writing", {
      async render() {
        return `<p data-project-copy="${state.currentProjectId}">${state.currentProjectId}</p>`
      },
    })

    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "writing"
    await window.router.renderCurrentView()

    api.projects.get
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ id: "project-b", title: "项目 B" })
    window.history.replaceState(null, "", "#workbench/project-b/writing")
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})
    await window.router.initRouter()
    warnSpy.mockRestore()

    expect(content.textContent).toContain("作品暂时加载失败")
    expect(content.textContent).not.toContain("project-a")
    content.querySelector('[data-action="retry-project-route"]').click()

    await vi.waitFor(() => expect(content.textContent).toContain("project-b"))
    expect(content.textContent).not.toContain("project-a")
    expect(api.projects.get).toHaveBeenCalledTimes(2)
  })

  it("abandons a temporary failed target when returning to the project list", async () => {
    const content = addWorkspace()
    window.router.registerView("writing", {
      async render() { return `<p>${state.currentProjectId}</p>` },
    })
    window.router.registerView("project", {
      async render() { return '<p id="returned-project-list">项目列表</p>' },
    })
    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "writing"
    await window.router.renderCurrentView()
    api.projects.get.mockRejectedValue(new Error("offline"))

    window.history.replaceState(null, "", "#workbench/project-b/writing")
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})
    await window.router.initRouter()
    warnSpy.mockRestore()
    content.querySelector('[data-action="return-project-list"]').click()

    await vi.waitFor(() => expect(content.querySelector("#returned-project-list")).not.toBeNull())
    expect(state.currentProjectId).toBeNull()
    expect(state.currentProject).toBeNull()
    expect(window.location.hash).toBe("#project")
  })

  it("disposes the source exactly once across a rapid A to B to C switch", async () => {
    const content = addWorkspace()
    const onLeave = vi.fn()
    window.router.registerView("world", {
      onLeave,
      async render() {
        return `<p data-project-copy="${state.currentProjectId}">${state.currentProjectId}</p>`
      },
    })
    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "world"
    state.currentSubView = "objects"
    window.history.replaceState(null, "", "#workbench/project-a/world/objects")
    await window.router.renderCurrentView()

    const pending = []
    api.projects.get.mockImplementation((projectId, options) => new Promise((resolve, reject) => {
      pending.push({ projectId, resolve, signal: options.signal })
      options.signal.addEventListener("abort", () => {
        const error = new Error("aborted")
        error.name = "AbortError"
        reject(error)
      }, { once: true })
    }))

    window.history.replaceState(null, "", "#workbench/project-b/world/objects")
    const projectB = window.router.initRouter()
    await vi.waitFor(() => expect(pending).toHaveLength(1))

    window.history.replaceState(null, "", "#workbench/project-c/world/objects")
    window.dispatchEvent(new PopStateEvent("popstate"))
    await vi.waitFor(() => expect(pending).toHaveLength(2))

    expect(pending[0].signal.aborted).toBe(true)
    expect(onLeave).toHaveBeenCalledTimes(1)
    expect(closeModal).toHaveBeenCalledTimes(1)
    expect(content.textContent).not.toContain("project-a")

    pending[1].resolve({ id: "project-c", title: "项目 C" })
    await vi.waitFor(() => expect(content.textContent).toContain("project-c"))
    await expect(projectB).resolves.toBe(false)

    expect(state.currentProjectId).toBe("project-c")
    expect(onLeave).toHaveBeenCalledTimes(1)
    expect(content.textContent).not.toContain("project-a")
    expect(content.textContent).not.toContain("project-b")
  })

  it("cancels a partially entered B renderer before C metadata settles", async () => {
    const content = addWorkspace()
    let releaseProjectBEnter
    const leaveOwners = []
    const renderOwners = []
    window.router.registerView("world", {
      onEnter() {
        if (state.currentProjectId !== "project-b") return Promise.resolve()
        return new Promise((resolve) => {
          releaseProjectBEnter = resolve
        })
      },
      onLeave() {
        leaveOwners.push(state.currentProjectId)
      },
      async render() {
        renderOwners.push(state.currentProjectId)
        return `<p data-project-copy="${state.currentProjectId}">${state.currentProjectId}</p>`
      },
    })
    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "world"
    state.currentSubView = "objects"
    window.history.replaceState(null, "", "#workbench/project-a/world/objects")
    await window.router.renderCurrentView()

    api.projects.get.mockImplementation(async (projectId) => ({
      id: projectId,
      title: projectId,
    }))
    window.history.replaceState(null, "", "#workbench/project-b/world/objects")
    const projectB = window.router.initRouter()
    await vi.waitFor(() => expect(releaseProjectBEnter).toBeTypeOf("function"))

    window.history.replaceState(null, "", "#workbench/project-c/world/objects")
    window.dispatchEvent(new PopStateEvent("popstate"))
    await vi.waitFor(() => expect(content.textContent).toContain("project-c"))

    releaseProjectBEnter()
    await expect(projectB).resolves.toBe(false)

    expect(leaveOwners).toEqual(["project-a", "project-b"])
    expect(renderOwners).toEqual(["project-a", "project-c"])
    expect(content.textContent).toContain("project-c")
    expect(content.textContent).not.toContain("project-b")
  })

  it("clears global selection as soon as a same-view project boundary is committed", async () => {
    const content = addWorkspace()
    let resolveProject
    window.router.registerView("writing", {
      onLeave: vi.fn(),
      async render() {
        return `<p>${state.currentProjectId}</p>`
      },
    })
    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "writing"
    state.selectedItem = { id: "old-row" }
    state.selectedItems = [{ id: "old-row" }]
    await window.router.renderCurrentView()

    api.projects.get.mockImplementation(() => new Promise((resolve) => {
      resolveProject = resolve
    }))
    window.history.replaceState(null, "", "#workbench/project-b/writing")
    const switching = window.router.initRouter()
    await vi.waitFor(() => expect(resolveProject).toBeTypeOf("function"))

    expect(state.selectedItem).toBeNull()
    expect(state.selectedItems).toEqual([])
    expect(content.querySelector(".loading-skeleton")).not.toBeNull()

    resolveProject({ id: "project-b", title: "项目 B" })
    await switching
  })

  it("cleans a partially entered target renderer when rendering fails", async () => {
    const content = addWorkspace()
    const sourceLeave = vi.fn()
    const targetLeave = vi.fn()
    window.router.registerView("world", {
      onLeave: sourceLeave,
      async render() { return "<p>项目 A 世界</p>" },
    })
    window.router.registerView("writing", {
      async onEnter() {
        throw new Error("target load failed")
      },
      onLeave: targetLeave,
      async render() { return "<p>不应渲染</p>" },
    })
    window.router.registerView("project", {
      async render() { return "<p>项目列表</p>" },
    })
    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "world"
    state.currentSubView = "objects"
    await window.router.renderCurrentView()

    api.projects.get.mockResolvedValue({ id: "project-b", title: "项目 B" })
    window.history.replaceState(null, "", "#workbench/project-b/writing")
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})
    await window.router.initRouter()
    errorSpy.mockRestore()

    expect(sourceLeave).toHaveBeenCalledTimes(1)
    expect(targetLeave).toHaveBeenCalledTimes(1)
    expect(content.textContent).toContain("页面加载失败")
    expect(content.textContent).not.toContain("不应渲染")

    await window.router.navigate("project", null, false)
    expect(targetLeave).toHaveBeenCalledTimes(1)
  })

  it("re-enters writing instead of reusing DOM across projects", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.append(content)

    const onEnter = vi.fn()
    const onLeave = vi.fn()
    window.router.registerView("writing", {
      onEnter,
      onLeave,
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

    await window.router.navigate("project", null, false)
    expect(onLeave).toHaveBeenCalledTimes(1)

    state.currentProjectId = "p2"
    await window.router.navigate("writing", null, false)

    expect(document.getElementById("writing-project").textContent).toBe("p2")
    expect(onEnter).toHaveBeenCalledTimes(enterCountAfterProjectOne + 1)
  })

  it("disposes and recreates writing when revisiting the route", async () => {
    const content = addWorkspace()
    const onLeave = vi.fn()
    const onEnter = vi.fn()
    const onRendered = vi.fn()

    window.router.registerView("writing", {
      onEnter,
      onLeave,
      onRendered,
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
    expect(onRendered).toHaveBeenCalledTimes(1)

    await window.router.navigate("world", null, false)
    expect(onLeave).toHaveBeenCalledTimes(1)

    await window.router.navigate("writing", null, false)
    expect(onEnter).toHaveBeenCalledTimes(2)
    expect(onRendered).toHaveBeenCalledTimes(2)
    expect(content.querySelector("#writing-state")?.textContent).toBe("章节树仍在")
  })
})

describe("subview memory", () => {
  it("normalizes the removed world/map entry to the world default", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.append(content)

    window.router.registerView("world", { async render() { return "" } })
    window.router.registerView("map", { async render() { return "" } })

    state.currentProjectId = "p1"
    state.currentProject = { id: "p1", title: "项目一" }
    state.currentView = "world"
    state.currentSubView = "objects"

    await window.router.navigate("world", "map", false)

    expect(state.currentView).toBe("world")
    expect(state.currentSubView).toBe("objects")
  })
})

describe("route guard and normalization", () => {
  it("uses the two-entry home as the empty-hash landing page", async () => {
    const content = addWorkspace()
    registerBasicView("home")
    window.history.replaceState(null, "", "#")

    await window.router.initRouter()

    expect(state.currentView).toBe("home")
    expect(state.currentSubView).toBeNull()
    expect(content.textContent).toContain("home:")
  })

  it("preserves the dynamic new-journey subview without requiring an author project", async () => {
    const content = addWorkspace()
    registerBasicView("journeys")
    window.history.replaceState(null, "", "#journeys/new")

    await window.router.initRouter()

    expect(state.currentView).toBe("journeys")
    expect(state.currentSubView).toBe("new")
    expect(state.currentProjectId).toBeNull()
    expect(content.textContent).toContain("journeys:new")
  })

  it("replace shares route normalization and canLeave while preserving history length", async () => {
    addWorkspace()
    const canLeave = vi.fn(() => true)
    window.router.registerView("map", {
      canLeave,
      async render() { return "<p>地图</p>" },
    })
    state.currentProjectId = "p1"
    state.currentProject = { id: "p1", title: "项目一" }
    api.projects.get.mockResolvedValue({ id: "p1", title: "项目一" })
    state.currentView = "map"
    const beforeLength = window.history.length

    const result = await window.router.replace(
      "map",
      null,
      new URLSearchParams({ tab: "atlas" }),
    )

    expect(result).toBe(true)
    expect(canLeave).toHaveBeenCalledTimes(1)
    expect(window.history.length).toBe(beforeLength)
    expect(window.location.hash).toBe("#workbench/p1/map?tab=atlas")
  })

  it("commits a local query without remounting and keeps it authoritative for refresh", async () => {
    addWorkspace()
    const onEnter = vi.fn()
    const render = vi.fn(async () => "<p>人物与设定</p>")
    window.router.registerView("world", { onEnter, render })
    state.currentProjectId = "p1"
    state.currentProject = { id: "p1", title: "项目一" }

    await window.router.replace("world", "objects", new URLSearchParams({ view: "table" }))
    expect(onEnter).toHaveBeenCalledTimes(1)
    expect(render).toHaveBeenCalledTimes(1)

    expect(window.router.commitCurrentQuery(new URLSearchParams({ view: "card" }))).toBe(true)
    expect(window.router.getCurrentQuery().get("view")).toBe("card")
    expect(window.location.hash).toBe("#workbench/p1/world/objects?view=card")
    expect(onEnter).toHaveBeenCalledTimes(1)
    expect(render).toHaveBeenCalledTimes(1)

    await window.router.refresh()
    expect(window.router.getCurrentQuery().get("view")).toBe("card")
  })

  it("keeps the current route when its renderer rejects leaving", async () => {
    addWorkspace()
    const canLeave = vi.fn(() => false)
    const onLeave = vi.fn()
    window.router.registerView("map", {
      canLeave,
      onLeave,
      async render() { return "<p>地图</p>" },
    })
    registerBasicView("project")
    state.currentProjectId = "p1"
    state.currentProject = { id: "p1", title: "项目一" }

    await window.router.navigate("map", null, false)
    const result = await window.router.navigate("project", null, false)

    expect(result).toBe(false)
    expect(canLeave).toHaveBeenCalledTimes(1)
    expect(onLeave).not.toHaveBeenCalled()
    expect(state.currentView).toBe("map")
    expect(state.currentProjectId).toBe("p1")
  })

  it("restores the rendered hash when browser navigation is rejected", async () => {
    addWorkspace()
    const canLeave = vi.fn(() => false)
    window.router.registerView("map", {
      canLeave,
      async render() { return "<p>地图</p>" },
    })
    registerBasicView("project")
    state.currentProjectId = "p1"
    state.currentProject = { id: "p1", title: "项目一" }
    await window.router.navigate("map")

    window.history.pushState(null, "", "#project")
    window.dispatchEvent(new PopStateEvent("popstate"))
    await vi.waitFor(() => expect(canLeave).toHaveBeenCalledTimes(1))

    expect(window.location.hash).toBe("#workbench/p1/map")
    expect(state.currentView).toBe("map")
  })

  it("keeps old project content when a cross-project popstate is rejected by the leave guard", async () => {
    const content = addWorkspace()
    const canLeave = vi.fn(() => false)
    window.router.registerView("world", {
      canLeave,
      async render() { return `<p id="guarded-project">${state.currentProjectId}</p>` },
    })
    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "world"
    state.currentSubView = "objects"
    window.history.replaceState(null, "", "#workbench/project-a/world/objects")
    await window.router.initRouter()

    window.history.replaceState(null, "", "#workbench/project-b/world/objects")
    window.dispatchEvent(new PopStateEvent("popstate"))
    await vi.waitFor(() => expect(canLeave).toHaveBeenCalledTimes(1))

    expect(window.location.hash).toBe("#workbench/project-a/world/objects")
    expect(content.querySelector("#guarded-project")?.textContent).toBe("project-a")
    expect(content.querySelector(".loading-skeleton")).toBeNull()
    expect(api.projects.get).not.toHaveBeenCalled()
  })

  it("keeps the source route intact when its project modal rejects navigation", async () => {
    const content = addWorkspace()
    const canLeave = vi.fn(() => true)
    const onLeave = vi.fn()
    window.router.registerView("world", {
      canLeave,
      onLeave,
      async render() { return `<p id="modal-guarded-project">${state.currentProjectId}</p>` },
    })
    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "world"
    state.currentSubView = "objects"
    window.history.replaceState(null, "", "#workbench/project-a/world/objects")
    await window.router.renderCurrentView()
    closeModal.mockReturnValue(false)

    window.history.replaceState(null, "", "#workbench/project-b/world/objects")
    window.dispatchEvent(new PopStateEvent("popstate"))
    await vi.waitFor(() => expect(closeModal).toHaveBeenCalledTimes(1))

    expect(canLeave).toHaveBeenCalledTimes(1)
    expect(closeModal).toHaveBeenCalledWith({ reason: "project-navigation" })
    expect(onLeave).not.toHaveBeenCalled()
    expect(api.projects.get).not.toHaveBeenCalled()
    expect(state.currentProjectId).toBe("project-a")
    expect(window.location.hash).toBe("#workbench/project-a/world/objects")
    expect(content.querySelector("#modal-guarded-project")?.textContent).toBe("project-a")
    expect(content.querySelector(".loading-skeleton")).toBeNull()
  })

  it("does not apply project-modal blocking when entering from the unscoped project catalog", async () => {
    const content = addWorkspace()
    window.router.registerView("project", {
      async render() { return "<p>项目列表</p>" },
    })
    window.router.registerView("writing", {
      async render() { return `<p id="catalog-opened-project">${state.currentProjectId}</p>` },
    })
    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "project"
    await window.router.renderCurrentView()
    closeModal.mockReturnValue(false)

    // ProjectView 的既有流程会先提交刚创建/选中的完整项目，再进入写作台。
    state.currentProjectId = "project-b"
    state.currentProject = { id: "project-b", title: "项目 B" }
    const result = await window.router.navigate("writing", null, false)

    expect(result).toBe(true)
    expect(closeModal).not.toHaveBeenCalled()
    expect(content.querySelector("#catalog-opened-project")?.textContent).toBe("project-b")
  })

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
    expect(toast).toHaveBeenCalledWith("请先选择作品后再进入该页面", "warning")
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
    window.history.replaceState(null, "", "#workbench/p1/world/not-real")

    await window.router.initRouter()

    expect(state.currentProjectId).toBe("p1")
    expect(state.currentView).toBe("world")
    expect(state.currentSubView).toBe("objects")
    expect(window.location.hash).toBe("#workbench/p1/world/objects")
  })

  it("defaults the outline workspace to the top-level story outline", async () => {
    addWorkspace()
    registerBasicView("outline")
    api.projects.get.mockResolvedValue({ id: "p1", title: "项目一" })
    window.history.replaceState(null, "", "#workbench/p1/outline")

    await window.router.initRouter()

    expect(state.currentView).toBe("outline")
    expect(state.currentSubView).toBe("story-outline")
    expect(window.location.hash).toBe("#workbench/p1/outline/story-outline")
    expect(window.router.getSubViewTitle("outline", "story-outline")).toBe("故事总览")
  })

  it("redirects legacy scene routes into the outline scene workbench", async () => {
    addWorkspace()
    registerBasicView("outline")
    api.projects.get.mockResolvedValue({ id: "p1", title: "项目一" })
    window.history.replaceState(null, "", "#workbench/p1/scene/s1")

    await window.router.initRouter()

    expect(state.currentView).toBe("outline")
    expect(state.currentSubView).toBe("scenes")
    expect(window.location.hash).toBe("#workbench/p1/outline/scenes?scene_id=s1")
    expect(window.router.getCurrentQuery().get("scene_id")).toBe("s1")
  })

  it.each(["foreshadowing", "reveals"])(
    "redirects legacy outline/%s routes to thread information progression",
    async (legacySubView) => {
      addWorkspace()
      registerBasicView("outline")
      api.projects.get.mockResolvedValue({ id: "p1", title: "项目一" })
      window.history.replaceState(
        null,
        "",
        `#workbench/p1/outline/${legacySubView}`,
      )

      await window.router.initRouter()

      expect(state.currentView).toBe("outline")
      expect(state.currentSubView).toBe("threads")
      expect(window.router.getCurrentQuery().get("information")).toBe(legacySubView)
      expect(window.location.hash).toBe(
        `#workbench/p1/outline/threads?information=${legacySubView}`,
      )
    },
  )

  it("redirects legacy context routes without a project to projects", async () => {
    addWorkspace()
    registerBasicView("project")
    registerBasicView("generate")
    window.history.replaceState(null, "", "#context")

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
    window.history.replaceState(null, "", "#workbench/p1/context")
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
    window.history.replaceState(null, "", "#llm")

    await window.router.initRouter()

    expect(state.currentView).toBe("settings")
    expect(state.currentSubView).toBeNull()
    expect(window.location.hash).toBe("#settings")

    api.projects.get.mockResolvedValue({ id: "p1", title: "项目一" })
    window.history.replaceState(null, "", "#workbench/p1/llm")
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
    window.history.replaceState(null, "", "#workbench/p1/world/candidates")

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
    window.history.replaceState(null, "", "#writing")

    await window.router.initRouter()

    expect(state.currentView).toBe("writing")
    expect(state.currentSubView).toBeNull()
    expect(window.location.hash).toBe("#workbench/p1/writing")
  })
})

describe("refresh forces project sync", () => {
  let App

  beforeAll(async () => {
    const appModule = await import("../app.js")
    App = appModule.default
  }, 15_000)

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

    expect(api.projects.get).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({
        signal: expect.any(AbortSignal),
        cache: "no-store",
      }),
    )
    expect(state.currentProject.title).toBe("New")
  })

  it("preserves the workspace position during a same-route refresh", async () => {
    const content = addWorkspace()
    const replaceChildren = content.replaceChildren.bind(content)
    vi.spyOn(content, "replaceChildren").mockImplementation((...nodes) => {
      replaceChildren(...nodes)
      if (nodes[0]?.classList?.contains("loading-skeleton")) content.scrollTop = 0
    })
    window.router.registerView("scroll-refresh", {
      async render() { return '<div style="height:2000px">long page</div>' },
    })
    state.currentView = "scroll-refresh"
    await window.router.renderCurrentView()
    content.scrollTop = 640

    await window.router.refresh()

    expect(content.scrollTop).toBe(640)
  })

  it("restores the focused local control during a same-route refresh", async () => {
    const content = addWorkspace()
    window.router.registerView("focus-refresh", {
      async render() {
        return '<label><input id="bulk-choice" type="checkbox" /> 批量选择</label>'
      },
    })
    state.currentView = "focus-refresh"
    await window.router.renderCurrentView()
    content.querySelector("#bulk-choice").focus()

    await window.router.refresh()

    expect(document.activeElement).toBe(content.querySelector("#bulk-choice"))
  })

  it("restores a focused row control identified by data attributes", async () => {
    const content = addWorkspace()
    window.router.registerView("row-focus-refresh", {
      async render() {
        return '<button data-action="select" data-id="row-2">选择</button>'
      },
    })
    state.currentView = "row-focus-refresh"
    await window.router.renderCurrentView()
    const original = content.querySelector('[data-action="select"]')
    original.focus()

    await window.router.refresh()

    const replacement = content.querySelector('[data-action="select"]')
    expect(replacement).not.toBe(original)
    expect(document.activeElement).toBe(replacement)
  })

  it("keeps the mounted page and metadata when same-project refresh fails temporarily", async () => {
    const content = addWorkspace()
    const onLeave = vi.fn()
    window.router.registerView("writing", {
      onLeave,
      async render() { return '<p id="retained-writing">未保存正文仍在</p>' },
    })
    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "writing"
    await window.router.renderCurrentView()
    api.projects.get.mockRejectedValue(new Error("offline"))

    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})
    const result = await window.router.refresh()
    warnSpy.mockRestore()

    expect(result).toBe(false)
    expect(onLeave).not.toHaveBeenCalled()
    expect(state.currentProject).toEqual({ id: "project-a", title: "项目 A" })
    expect(content.querySelector("#retained-writing")?.textContent).toBe("未保存正文仍在")
    expect(content.textContent).not.toContain("项目暂时加载失败")
    expect(toast).toHaveBeenCalledWith(
      "项目信息加载失败，当前页面已保留，可稍后重试",
      "warning",
    )
  })

  it("fails closed when same-project refresh discovers that access is gone", async () => {
    const content = addWorkspace()
    const onLeave = vi.fn()
    window.router.registerView("writing", {
      onLeave,
      async render() { return '<p id="revoked-writing">旧授权正文</p>' },
    })
    state.currentProjectId = "project-a"
    state.currentProject = { id: "project-a", title: "项目 A" }
    state.currentView = "writing"
    await window.router.renderCurrentView()
    const forbidden = new Error("forbidden")
    forbidden.status = 403
    api.projects.get.mockRejectedValue(forbidden)

    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})
    const result = await window.router.refresh()
    warnSpy.mockRestore()

    expect(result).toBe(false)
    expect(onLeave).toHaveBeenCalledTimes(1)
    expect(closeModal).toHaveBeenCalledWith({ force: true })
    expect(state.currentProjectId).toBeNull()
    expect(state.currentProject).toBeNull()
    expect(content.querySelector("#revoked-writing")).toBeNull()
    expect(content.textContent).toContain("无法打开这部作品")
    expect(content.querySelector('[data-action="retry-project-route"]')).toBeNull()
  })

  it("re-fetches full project metadata after restoring a legacy project object summary", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.append(content)

    localStorage.clear()
    state.currentProjectId = null
    state.currentProject = null
    window.history.replaceState(null, "", "#workbench/p1/writing")
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

    expect(api.projects.get).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({
        signal: expect.any(AbortSignal),
        cache: "no-store",
      }),
    )
    expect(state.currentProject).toEqual({
      id: "p1",
      title: "Fetched",
      genre: "fantasy",
      tone: "warm",
    })
  })

  it("keeps the newest A metadata across an A to B to A out-of-order switch", async () => {
    addWorkspace()
    registerBasicView("writing")
    state.currentView = "writing"
    state.currentSubView = null

    const pending = []
    api.projects.get.mockImplementation((projectId, options) => new Promise((resolve) => {
      pending.push({ projectId, resolve, signal: options.signal })
    }))

    state.currentProjectId = "project-a"
    const firstARefresh = window.router.refresh()
    await vi.waitFor(() => expect(pending).toHaveLength(1))

    state.currentProjectId = "project-b"
    const projectBRefresh = window.router.refresh()
    await vi.waitFor(() => expect(pending).toHaveLength(2))

    state.currentProjectId = "project-a"
    const latestARefresh = window.router.refresh()
    await vi.waitFor(() => expect(pending).toHaveLength(3))

    expect(pending.map((item) => item.projectId)).toEqual([
      "project-a",
      "project-b",
      "project-a",
    ])
    expect(pending[0].signal.aborted).toBe(true)
    expect(pending[1].signal.aborted).toBe(true)
    expect(pending[2].signal.aborted).toBe(false)

    pending[2].resolve({ id: "project-a", title: "最新 A" })
    await latestARefresh
    pending[1].resolve({ id: "project-b", title: "晚到 B" })
    await projectBRefresh
    pending[0].resolve({ id: "project-a", title: "最旧 A" })
    await firstARefresh

    expect(state.currentProjectId).toBe("project-a")
    expect(state.currentProject).toEqual({ id: "project-a", title: "最新 A" })
    expect(toast).not.toHaveBeenCalledWith(
      "项目信息加载失败，可稍后重试",
      "warning",
    )
  })

  it("does not let a superseded navigation overwrite the latest route or hash", async () => {
    addWorkspace()
    registerBasicView("writing")
    registerBasicView("world")

    const pending = []
    api.projects.get.mockImplementation((projectId, options) => new Promise((resolve) => {
      pending.push({ projectId, resolve, signal: options.signal })
    }))

    state.currentProjectId = "project-b"
    const staleNavigation = window.router.navigate("writing")
    await vi.waitFor(() => expect(pending).toHaveLength(1))

    state.currentProjectId = "project-a"
    const latestNavigation = window.router.navigate("world", "objects")
    await vi.waitFor(() => expect(pending).toHaveLength(2))

    pending[1].resolve({ id: "project-a", title: "项目 A" })
    await expect(latestNavigation).resolves.toBe(true)
    pending[0].resolve({ id: "project-b", title: "项目 B" })
    await expect(staleNavigation).resolves.toBe(false)

    expect(state.currentProjectId).toBe("project-a")
    expect(state.currentProject).toEqual({ id: "project-a", title: "项目 A" })
    expect(state.currentView).toBe("world")
    expect(state.currentSubView).toBe("objects")
    expect(window.location.hash).toBe("#workbench/project-a/world/objects")
  })

  it("silently settles a request rejected because a newer sync aborted it", async () => {
    addWorkspace()
    registerBasicView("writing")
    registerBasicView("project")
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})

    api.projects.get.mockImplementation((_projectId, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => {
        const err = new Error("request cancelled")
        err.name = "AbortError"
        reject(err)
      }, { once: true })
    }))

    state.currentProjectId = "project-a"
    const staleRefresh = window.router.refresh()
    await vi.waitFor(() => expect(api.projects.get).toHaveBeenCalledTimes(1))
    const latestNavigation = window.router.navigate("project", null, false)

    await expect(staleRefresh).resolves.toBe(false)
    await expect(latestNavigation).resolves.toBe(true)
    expect(warnSpy).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalledWith(
      "项目信息加载失败，可稍后重试",
      "warning",
    )
    warnSpy.mockRestore()
  })

  it("lets popstate supersede an in-flight initial route", async () => {
    addWorkspace()
    registerBasicView("writing")
    registerBasicView("world")

    const pending = []
    api.projects.get.mockImplementation((projectId, options) => new Promise((resolve) => {
      pending.push({ projectId, resolve, signal: options.signal })
    }))

    window.history.replaceState(null, "", "#workbench/project-a/writing")
    const initializing = window.router.initRouter()
    await vi.waitFor(() => expect(pending).toHaveLength(1))

    window.history.replaceState(null, "", "#workbench/project-b/world/objects")
    window.dispatchEvent(new PopStateEvent("popstate"))
    await vi.waitFor(() => expect(pending).toHaveLength(2))
    expect(pending[0].signal.aborted).toBe(true)

    pending[1].resolve({ id: "project-b", title: "项目 B" })
    await vi.waitFor(() => {
      expect(state.currentProject).toEqual({ id: "project-b", title: "项目 B" })
      expect(state.currentView).toBe("world")
    })
    pending[0].resolve({ id: "project-a", title: "项目 A" })
    await expect(initializing).resolves.toBe(false)

    expect(state.currentProjectId).toBe("project-b")
    expect(state.currentSubView).toBe("objects")
    expect(window.location.hash).toBe("#workbench/project-b/world/objects")
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
