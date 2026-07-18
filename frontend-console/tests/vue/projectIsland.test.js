/**
 * projectIsland 注册与 load 测试。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../vue/bridge/index.js"
import "../../vue/projectIsland.js"

const views = globalThis.router.registerView.mock.calls.reduce(
  (map, [name, island]) => ({ ...map, [name]: island }),
  {},
)

function makeState(overrides = {}) {
  return {
    projects: [],
    currentProjectId: null,
    currentProject: null,
    viewStates: {},
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("projectIsland", () => {
  it("注册 project 视图", () => {
    expect(views.project).toBeTruthy()
  })

  it("load 拉取项目列表并同步 currentProject", async () => {
    const state = makeState({ currentProjectId: "p1" })
    setBridgeOverrides({ state })
    globalThis.api.projects.list = vi.fn(async () => ({
      items: [{ id: "p1", title: "匹配项目" }, { id: "p2", title: "其他" }],
    }))
    await views.project.onEnter()
    expect(state.projects).toHaveLength(2)
    expect(state.currentProject.title).toBe("匹配项目")
  })

  it("currentProjectId 失效时清理选择与 localStorage", async () => {
    const state = makeState({ currentProjectId: "gone", currentProject: { id: "gone" } })
    state.viewStates.writing = { currentChapter: 3 }
    localStorage.setItem("novel_currentProjectId", "gone")
    setBridgeOverrides({ state })
    globalThis.api.projects.list = vi.fn(async () => ({ items: [{ id: "p1" }] }))
    await views.project.onEnter()
    expect(state.currentProjectId).toBeNull()
    expect(state.currentProject).toBeNull()
    expect(state.viewStates.writing).toBeUndefined()
    expect(localStorage.getItem("novel_currentProjectId")).toBeNull()
  })

  it("加载失败返回 loadError 且不抛异常", async () => {
    const state = makeState()
    setBridgeOverrides({ state })
    globalThis.api.projects.list = vi.fn(async () => {
      throw new Error("连接被拒绝")
    })
    await views.project.onEnter()
    // island 的 loadedProps 经 onRendered 挂载使用，这里直接验证 render/mount 不崩即可
    document.body.innerHTML = '<div id="workspace-content"></div>'
    const content = document.getElementById("workspace-content")
    content.innerHTML = views.project.render()
    await views.project.onRendered()
    expect(content.querySelector(".project-catalog-state")).toBeTruthy()
    expect(content.textContent).toContain("连接被拒绝")
    views.project.onLeave()
  })

  it("正常加载后挂载渲染卡片", async () => {
    const state = makeState()
    setBridgeOverrides({ state })
    globalThis.api.projects.list = vi.fn(async () => ({
      items: [{ id: "p1", title: "星际旅人", status: "active" }],
    }))
    await views.project.onEnter()
    document.body.innerHTML = '<div id="workspace-content"></div>'
    const content = document.getElementById("workspace-content")
    content.innerHTML = views.project.render()
    await views.project.onRendered()
    expect(content.querySelector(".project-card[data-id='p1']")).toBeTruthy()
    views.project.onLeave()
  })
})
