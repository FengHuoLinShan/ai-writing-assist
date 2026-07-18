/**
 * RagSearchView 组件测试 — 表单初始化、提交、路由恢复（对应原 ragView.test.js
 * 的路由恢复 round-trip 用例）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { mount } from "@vue/test-utils"
import RagSearchView from "../../../vue/views/rag/RagSearchView.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { ragSearchSession, resetRagSearchSession } from "../../../vue/views/rag/ragSearchSession.js"

function makeHits(count) {
  return Array.from({ length: count }, (_, index) => ({
    kind: "manuscript",
    title: `命中 ${index + 1}`,
    snippet: `证据 ${index + 1}`,
    chapter_index: index + 1,
    source_ref: { content_mode: "canonical", chapter_index: index + 1, version_number: 1 },
  }))
}

function overrideRouterQuery(queryString) {
  const state = { currentProjectId: "p1", searchQuery: "", viewStates: {} }
  setBridgeOverrides({
    state,
    router: {
      ...globalThis.router,
      getCurrentQuery: () => new URLSearchParams(queryString),
      navigate: vi.fn(async () => true),
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  resetRagSearchSession()
  globalThis.api.context.searchEvidence = vi.fn(async () => ({
    total: 3,
    hits: makeHits(3),
    warnings: [],
    degraded: false,
  }))
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("表单初始化（路由为权威来源）", () => {
  it("从路由 query 初始化表单", () => {
    overrideRouterQuery("q=旧塔&kind=literal&content_mode=working&scope=world")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    expect(wrapper.find("#rag-search-input").element.value).toBe("旧塔")
    expect(wrapper.find("#rag-search-kind").element.value).toBe("literal")
    expect(wrapper.find("#rag-content-mode").element.value).toBe("working")
  })

  it("路由含高级筛选时摘要展开", () => {
    overrideRouterQuery("q=旧塔&chapter_from=2&chapter_to=5")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    expect(wrapper.find(".rag-advanced-filters").attributes("open")).toBeDefined()
    expect(wrapper.find('[data-role="rag-advanced-summary"]').text()).toContain("第 2–5 章")
  })
})

describe("提交", () => {
  it("签名不同走路由导航", async () => {
    overrideRouterQuery("")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    await wrapper.find("#rag-search-input").setValue("旧塔")
    await wrapper.find('[data-action="do-search"]').trigger("click")

    const router = (await import("../../../vue/bridge/index.js")).getRouter()
    expect(router.navigate).toHaveBeenCalledWith("rag", "search", true, expect.any(URLSearchParams))
    const route = router.navigate.mock.calls[0][3]
    expect(route.get("q")).toBe("旧塔")
    expect(route.get("kind")).toBe("smart")
  })

  it("签名未变时本地直接搜索，不重复导航", async () => {
    overrideRouterQuery("q=旧塔&kind=smart&content_mode=canonical&visibility=author&scope=manuscript")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    // 挂载时恢复已执行一次搜索，清空调用记录再提交相同条件
    await vi.waitFor(() => expect(globalThis.api.context.searchEvidence).toHaveBeenCalled())
    globalThis.api.context.searchEvidence.mockClear()

    const router = (await import("../../../vue/bridge/index.js")).getRouter()
    await wrapper.find('[data-action="do-search"]').trigger("click")
    await vi.waitFor(() => expect(globalThis.api.context.searchEvidence).toHaveBeenCalled())
    expect(router.navigate).not.toHaveBeenCalled()
  })

  it("校验失败仅警告不搜索", async () => {
    overrideRouterQuery("")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    await wrapper.find("#rag-search-input").setValue("旧塔")
    await wrapper.find("#rag-visibility-mode").setValue("reader")
    await wrapper.find('[data-action="do-search"]').trigger("click")
    expect(globalThis.toast).toHaveBeenCalledWith("读者/角色视角必须设置可见截止章", "warning")
    expect(globalThis.api.context.searchEvidence).not.toHaveBeenCalled()
  })
})

describe("路由恢复", () => {
  it("挂载时按路由恢复并渲染结果", async () => {
    overrideRouterQuery("q=旧塔&kind=smart&content_mode=canonical&visibility=author&scope=manuscript")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    await vi.waitFor(() => {
      expect(wrapper.findAll(".rag-result-card")).toHaveLength(3)
    })
    expect(wrapper.find(".rag-result-count").text()).toContain("找到 3")
    // signature 为 URLSearchParams 序列化结果（中文按百分号编码）
    expect(ragSearchSession.lastExecutedRouteSignature).toBe(
      new URLSearchParams("q=旧塔&kind=smart&content_mode=canonical&visibility=author&scope=manuscript").toString(),
    )
  })

  it("签名未变且有结果时不重复搜索", async () => {
    ragSearchSession.lastExecutedRouteSignature = new URLSearchParams("q=旧塔").toString()
    ragSearchSession.lastSearchPayload = { query: "旧塔", search_kind: "smart" }
    ragSearchSession.hits = makeHits(2)
    ragSearchSession.visibleCount = 2
    ragSearchSession.total = 2
    overrideRouterQuery("q=旧塔")
    mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(globalThis.api.context.searchEvidence).not.toHaveBeenCalled()
  })

  it("路由无关键词时清空结果", async () => {
    ragSearchSession.hits = makeHits(2)
    ragSearchSession.lastSearchPayload = { query: "旧塔" }
    overrideRouterQuery("")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(ragSearchSession.hits).toEqual([])
    expect(wrapper.find(".rag-search-empty").text()).toContain("输入关键词后搜索")
  })
})

describe("结果交互", () => {
  it("打开结果卡显示抽屉原文", async () => {
    overrideRouterQuery("q=旧塔&kind=smart&content_mode=canonical&visibility=author&scope=manuscript")
    globalThis.api.context.readEvidence = vi.fn(async () => ({
      title: "第一章",
      text: "旧塔的铜铃在夜里响起。",
      highlight_start: 3,
      highlight_end: 5,
      source_ref: { chapter_index: 1, version_number: 1 },
      scene_refs: [],
      object_refs: [],
      warnings: [],
    }))
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    await vi.waitFor(() => expect(wrapper.findAll(".rag-result-card")).toHaveLength(3))
    await wrapper.find('[data-action="open-hit"]').trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.find("#rag-evidence-drawer").text()).toContain("旧塔的铜铃在夜里响起")
    })
    expect(wrapper.find("#rag-evidence-drawer mark").text()).toBe("铜铃")

    await wrapper.find('[data-action="close-drawer"]').trigger("click")
    expect(wrapper.find("#rag-evidence-drawer").attributes("hidden")).toBeDefined()
  })
})
