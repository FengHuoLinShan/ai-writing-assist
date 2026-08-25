/**
 * ragIsland 注册与 load 测试。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../vue/bridge/index.js"
import {
  ragSearchSession,
  scopeRagSessionToProject,
} from "../../vue/views/rag/ragSearchSession.js"
import "../../vue/ragIsland.js"

const views = globalThis.router.registerView.mock.calls.reduce(
  (map, [name, island]) => ({ ...map, [name]: island }),
  {},
)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("ragIsland", () => {
  it("注册 rag 视图", () => {
    expect(views.rag).toBeTruthy()
  })

  it("同项目 load 保留检索会话并拉取 status/characters/scenes", async () => {
    scopeRagSessionToProject("p1")
    ragSearchSession.hits = [{ title: "残留" }]
    ragSearchSession.lastExecutedRouteSignature = "stale"
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    globalThis.api.rag.status = vi.fn(async () => ({
      total: 12,
      embedding_failed_count: 0,
      retryable_embedding_count: 0,
      warnings: [],
      items: [],
      index_freshness: { by_content_mode: { canonical: { fresh: 2, total: 3 } } },
    }))
    globalThis.api.context.evidenceHealth = vi.fn(async () => ({ health_state: "healthy" }))
    globalThis.api.world.listCharacters = vi.fn(async () => ({ items: [{ id: "c1", name: "林晚" }], total: 1 }))
    globalThis.api.outline.listScenesOrdered = vi.fn(async () => [{ id: "s1", title: " Scene 1 " }])

    await views.rag.onEnter()
    expect(ragSearchSession.hits).toEqual([{ title: "残留" }])
    expect(ragSearchSession.lastExecutedRouteSignature).toBe("stale")

    document.body.innerHTML = '<div id="workspace-content"></div>'
    const content = document.getElementById("workspace-content")
    content.innerHTML = views.rag.render()
    await views.rag.onRendered()
    // 默认进入 search 子视图（state.currentSubView 未设置）
    expect(content.querySelector("#rag-search-input")).toBeTruthy()
    expect(content.querySelector(".view-header")).toBeNull()
    expect(content.querySelector(".subnav")).toBeNull()
    expect(content.querySelector('[data-action="nav-search"]')).toBeNull()
    expect(content.querySelector('[data-action="nav-status"]')).toBeNull()
    views.rag.onLeave()
  })

  it("并行启动首屏状态、证据、人物和 Scene 请求", async () => {
    setBridgeOverrides({ state: { currentProjectId: "p-concurrent" } })
    let resolveStatus
    globalThis.api.rag.status = vi.fn(() => new Promise((resolve) => {
      resolveStatus = resolve
    }))
    globalThis.api.context.evidenceHealth = vi.fn(async () => null)
    globalThis.api.world.listCharacters = vi.fn(async () => ({ items: [], total: 0 }))
    globalThis.api.outline.listScenesOrdered = vi.fn(async () => [])

    const entering = views.rag.onEnter()

    expect(globalThis.api.rag.status).toHaveBeenCalledWith("p-concurrent")
    expect(globalThis.api.context.evidenceHealth).toHaveBeenCalledWith(
      "p-concurrent",
      "canonical",
      24,
    )
    expect(globalThis.api.world.listCharacters).toHaveBeenCalledWith({
      novel_id: "p-concurrent",
      skip: 0,
      limit: 50,
    })
    expect(globalThis.api.outline.listScenesOrdered).toHaveBeenCalledWith("p-concurrent")

    resolveStatus({ total: 0, warnings: [], items: [] })
    await entering
  })

  it("同项目查找与状态往返保留 URL、未提交筛选和结果，切换项目才清空", async () => {
    const state = {
      currentProjectId: "p-session",
      currentSubView: "search",
      searchQuery: "",
      viewStates: {},
    }
    setBridgeOverrides({ state })
    const route = new URLSearchParams(
      "q=旧塔&kind=smart&content_mode=canonical&visibility=author&scope=manuscript",
    )
    globalThis.router.navigate("rag", "search", true, route)
    globalThis.api.rag.status = vi.fn(async () => ({
      total: 0,
      degraded: true,
      warnings: ["需要修复"],
      items: [],
    }))
    globalThis.api.context.evidenceHealth = vi.fn(async () => null)
    globalThis.api.context.searchEvidence = vi.fn(async () => ({
      total: 1,
      hits: [{
        kind: "manuscript",
        title: "第一章",
        snippet: "旧塔的铜铃。",
        chapter_index: 1,
        source_ref: { content_mode: "canonical", chapter_index: 1, version_number: 1 },
      }],
      warnings: [],
      degraded: false,
    }))
    globalThis.api.world.listCharacters = vi.fn(async () => ({ items: [], total: 0 }))
    globalThis.api.outline.listScenesOrdered = vi.fn(async () => [])

    document.body.innerHTML = '<div id="workspace-content"></div>'
    const content = document.getElementById("workspace-content")
    await views.rag.onEnter()
    content.innerHTML = views.rag.render()
    await views.rag.onRendered()
    await vi.waitFor(() => expect(content.querySelectorAll(".rag-result-card")).toHaveLength(1))

    const searchInput = content.querySelector("#rag-search-input")
    searchInput.value = "未提交的新词"
    searchInput.dispatchEvent(new Event("input", { bubbles: true }))
    const chapterFrom = content.querySelector("#rag-chapter-from")
    chapterFrom.value = "3"
    chapterFrom.dispatchEvent(new Event("input", { bubbles: true }))
    await Promise.resolve()

    content.querySelector('[data-action="nav-status"]').click()
    expect(globalThis.router.getCurrentQuery().toString()).toBe(route.toString())
    state.currentSubView = "status"
    await views.rag.onEnter()
    content.innerHTML = views.rag.render()
    await views.rag.onRendered()

    content.querySelector('.rag-repair-card [data-action="nav-search"]').click()
    expect(globalThis.router.getCurrentQuery().toString()).toBe(route.toString())
    state.currentSubView = "search"
    await views.rag.onEnter()
    content.innerHTML = views.rag.render()
    await views.rag.onRendered()

    expect(content.querySelector("#rag-search-input").value).toBe("未提交的新词")
    expect(content.querySelector("#rag-chapter-from").value).toBe("3")
    expect(content.querySelectorAll(".rag-result-card")).toHaveLength(1)
    expect(globalThis.api.context.searchEvidence).toHaveBeenCalledTimes(1)

    state.currentProjectId = "p-other"
    await views.rag.onEnter()
    expect(ragSearchSession.ownerProjectId).toBe("p-other")
    expect(ragSearchSession.hits).toEqual([])
    expect(ragSearchSession.formState).toBeNull()
    views.rag.onLeave()
  })

  it("无项目时仅返回不可用标记", async () => {
    setBridgeOverrides({ state: { currentProjectId: null, currentSubView: "status" } })
    await views.rag.onEnter()
    document.body.innerHTML = '<div id="workspace-content"></div>'
    const content = document.getElementById("workspace-content")
    content.innerHTML = views.rag.render()
    await views.rag.onRendered()
    expect(content.textContent).toContain("暂时无法连接查找服务")
    views.rag.onLeave()
  })

  it("status 接口失败时降级为未连接而不抛出", async () => {
    setBridgeOverrides({ state: { currentProjectId: "p1", currentSubView: "status" } })
    globalThis.api.rag.status = vi.fn(async () => {
      throw new Error("网络错误")
    })
    globalThis.api.context.evidenceHealth = vi.fn(async () => null)
    globalThis.api.world.listCharacters = vi.fn(async () => ({ items: [], total: 0 }))
    globalThis.api.outline.listScenesOrdered = vi.fn(async () => [])
    await views.rag.onEnter()
    expect(globalThis.api.world.listCharacters).not.toHaveBeenCalled()
    expect(globalThis.api.outline.listScenesOrdered).not.toHaveBeenCalled()
    document.body.innerHTML = '<div id="workspace-content"></div>'
    const content = document.getElementById("workspace-content")
    content.innerHTML = views.rag.render()
    await views.rag.onRendered()
    expect(content.textContent).toContain("暂时无法连接查找服务")
    views.rag.onLeave()
  })

  it("worker 已就绪时不触发预热", async () => {
    setBridgeOverrides({ state: { currentProjectId: "p-healthy" } })
    globalThis.api.rag.status = vi.fn(async () => ({
      total: 5,
      embedding_runtime: { started: true, healthy: true, cache_stats: {} },
      warnings: [],
      items: [],
    }))
    globalThis.api.context.evidenceHealth = vi.fn(async () => null)
    globalThis.api.world.listCharacters = vi.fn(async () => ({ items: [], total: 0 }))
    globalThis.api.outline.listScenesOrdered = vi.fn(async () => [])
    globalThis.api.rag.prewarm = vi.fn()
    await views.rag.onEnter()
    expect(globalThis.api.rag.prewarm).not.toHaveBeenCalled()
  })

  it("有片段且 worker 未就绪时触发后台预热，同项目不重复发起", async () => {
    setBridgeOverrides({ state: { currentProjectId: "p-need-prewarm" } })
    globalThis.api.rag.status = vi.fn(async () => ({
      total: 5,
      embedding_runtime: { started: false, healthy: false, cache_stats: {} },
      warnings: [],
      items: [],
    }))
    globalThis.api.context.evidenceHealth = vi.fn(async () => null)
    globalThis.api.world.listCharacters = vi.fn(async () => ({ items: [], total: 0 }))
    globalThis.api.outline.listScenesOrdered = vi.fn(async () => [])
    globalThis.api.rag.prewarm = vi.fn(async () => ({
      status: "ready",
      embedding_dim: 1024,
      cache_stats: {},
    }))

    await views.rag.onEnter()
    expect(globalThis.api.rag.prewarm).toHaveBeenCalledTimes(1)
    // 子标签切换再次 onEnter：ready 去重，不重复发起（P2 回归）
    await views.rag.onEnter()
    expect(globalThis.api.rag.prewarm).toHaveBeenCalledTimes(1)
    views.rag.onLeave()
  })
})
