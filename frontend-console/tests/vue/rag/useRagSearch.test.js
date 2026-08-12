/**
 * useRagSearch 测试 — doSearch 门禁与结果写入（对应原 ragView.test.js 的
 * 搜索执行 / generation 取消 / 渐进加载用例）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { effectScope } from "vue"
import { useRagSearch } from "../../../vue/views/rag/useRagSearch.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { ragSearchSession, resetRagSearchSession } from "../../../vue/views/rag/ragSearchSession.js"

function makeForm(overrides = {}) {
  return {
    searchKind: "smart",
    contentMode: "canonical",
    visibilityMode: "author",
    scopes: ["manuscript"],
    includePending: false,
    ...overrides,
  }
}

function makeHits(count) {
  return Array.from({ length: count }, (_, index) => ({
    kind: "manuscript",
    title: `命中 ${index + 1}`,
    snippet: `证据 ${index + 1}`,
    chapter_index: index + 1,
    source_ref: { content_mode: "canonical", chapter_index: index + 1, version_number: 1 },
  }))
}

beforeEach(() => {
  vi.clearAllMocks()
  resetRagSearchSession()
  setBridgeOverrides({ state: { currentProjectId: "p1" } })
  globalThis.api.context.searchEvidence = vi.fn(async () => ({
    total: 58,
    hits: makeHits(58),
    warnings: [],
    degraded: false,
  }))
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("doSearch", () => {
  it("成功后写入会话结果并按 20 条分页", async () => {
    const scope = effectScope()
    const { doSearch } = scope.run(() => useRagSearch())
    await doSearch("旧塔", { routeSignature: "q=旧塔", formState: makeForm() })

    expect(ragSearchSession.hits).toHaveLength(58)
    expect(ragSearchSession.visibleCount).toBe(20)
    expect(ragSearchSession.total).toBe(58)
    expect(ragSearchSession.query).toBe("旧塔")
    expect(ragSearchSession.lastExecutedRouteSignature).toBe("q=旧塔")
    expect(ragSearchSession.lastSearchPayload.search_kind).toBe("smart")
    scope.stop()
  })

  it("literal 走 grepEvidence 并换写 pattern/limit", async () => {
    globalThis.api.context.grepEvidence = vi.fn(async () => ({ hits: [], total: 0 }))
    const scope = effectScope()
    const { doSearch } = scope.run(() => useRagSearch())
    await doSearch("旧塔", { formState: makeForm({ searchKind: "literal" }) })

    expect(globalThis.api.context.grepEvidence).toHaveBeenCalledWith(
      expect.objectContaining({ pattern: "旧塔", limit: 100, group_by_chapter: true }),
      expect.any(Object),
    )
    expect(globalThis.api.context.searchEvidence).not.toHaveBeenCalled()
    scope.stop()
  })

  it("只携带当前项目的写作 Scene 快照", async () => {
    const state = {
      currentProjectId: "p1",
      viewStates: {
        writing: { projectId: "p1", currentSceneId: "scene-p1" },
      },
      _currentSceneId: "legacy-scene",
    }
    setBridgeOverrides({ state })
    const scope = effectScope()
    const { doSearch } = scope.run(() => useRagSearch())

    await doSearch("旧塔", { formState: makeForm() })
    expect(globalThis.api.context.searchEvidence).toHaveBeenLastCalledWith(
      expect.objectContaining({ context_scene_id: "scene-p1" }),
      expect.any(Object),
    )

    state.currentProjectId = "p2"
    globalThis.api.context.searchEvidence.mockClear()
    await doSearch("铜铃", { formState: makeForm() })
    expect(globalThis.api.context.searchEvidence).toHaveBeenLastCalledWith(
      expect.objectContaining({ context_scene_id: null, novel_id: "p2" }),
      expect.any(Object),
    )
    scope.stop()
  })

  it("校验失败时 toast 并清空结果", async () => {
    const scope = effectScope()
    const { doSearch } = scope.run(() => useRagSearch())
    await doSearch("旧塔", { formState: makeForm({ visibilityMode: "reader" }) })

    expect(globalThis.toast).toHaveBeenCalledWith("读者/角色视角必须设置可见截止章", "warning")
    expect(ragSearchSession.hits).toEqual([])
    expect(globalThis.api.context.searchEvidence).not.toHaveBeenCalled()
    scope.stop()
  })

  it("接口失败时保留错误状态（不伪装空结果）", async () => {
    globalThis.api.context.searchEvidence = vi.fn(async () => {
      throw Object.assign(new Error("检索超时"), { status: 504 })
    })
    const scope = effectScope()
    const { doSearch, searchError } = scope.run(() => useRagSearch())
    await doSearch("旧塔", { formState: makeForm() })
    expect(searchError.value).toBeTruthy()
    expect(searchError.value.searchKind).toBe("smart")
    expect(ragSearchSession.lastExecutedRouteSignature).toBe("")
    scope.stop()
  })

  it("generation 门禁：后发请求不回写已被取代的结果", async () => {
    let resolveFirst
    const first = new Promise((resolve) => { resolveFirst = resolve })
    globalThis.api.context.searchEvidence = vi.fn()
      .mockImplementationOnce(() => first)
      .mockImplementationOnce(async () => ({ total: 3, hits: makeHits(3) }))
    const scope = effectScope()
    const { doSearch } = scope.run(() => useRagSearch())

    const p1 = doSearch("第一次", { formState: makeForm() })
    const p2 = doSearch("第二次", { formState: makeForm() })
    resolveFirst({ total: 99, hits: makeHits(99) })
    await Promise.all([p1, p2])

    expect(ragSearchSession.query).toBe("第二次")
    expect(ragSearchSession.hits).toHaveLength(3)
    scope.stop()
  })

  it("项目切换后晚到响应被丢弃", async () => {
    const state = { currentProjectId: "p1" }
    setBridgeOverrides({ state })
    let resolveSearch
    globalThis.api.context.searchEvidence = vi.fn(() => new Promise((resolve) => { resolveSearch = resolve }))
    const scope = effectScope()
    const { doSearch } = scope.run(() => useRagSearch())
    const pending = doSearch("旧塔", { formState: makeForm() })
    state.currentProjectId = "p2"
    resolveSearch({ total: 5, hits: makeHits(5) })
    await pending
    expect(ragSearchSession.hits).toEqual([])
    scope.stop()
  })
})

describe("loadMore", () => {
  it("每次 +20，封顶 hits 总数", async () => {
    const scope = effectScope()
    const { doSearch, loadMore } = scope.run(() => useRagSearch())
    await doSearch("旧塔", { formState: makeForm() })
    loadMore()
    expect(ragSearchSession.visibleCount).toBe(40)
    loadMore()
    expect(ragSearchSession.visibleCount).toBe(58)
    loadMore()
    expect(ragSearchSession.visibleCount).toBe(58)
    scope.stop()
  })
})
