/**
 * ragIsland 注册与 load 测试。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../vue/bridge/index.js"
import { ragSearchSession } from "../../vue/views/rag/ragSearchSession.js"
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

  it("load 重置检索会话并拉取 status/characters/scenes", async () => {
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
    expect(ragSearchSession.hits).toEqual([])
    expect(ragSearchSession.lastExecutedRouteSignature).toBe("")

    document.body.innerHTML = '<div id="workspace-content"></div>'
    const content = document.getElementById("workspace-content")
    content.innerHTML = views.rag.render()
    await views.rag.onRendered()
    // 默认进入 search 子视图（state.currentSubView 未设置）
    expect(content.querySelector("#rag-search-input")).toBeTruthy()
    views.rag.onLeave()
  })

  it("无项目时仅返回不可用标记", async () => {
    setBridgeOverrides({ state: { currentProjectId: null, currentSubView: "status" } })
    await views.rag.onEnter()
    document.body.innerHTML = '<div id="workspace-content"></div>'
    const content = document.getElementById("workspace-content")
    content.innerHTML = views.rag.render()
    await views.rag.onRendered()
    expect(content.textContent).toContain("与服务器连接断开")
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
    document.body.innerHTML = '<div id="workspace-content"></div>'
    const content = document.getElementById("workspace-content")
    content.innerHTML = views.rag.render()
    await views.rag.onRendered()
    expect(content.textContent).toContain("与服务器连接断开")
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
