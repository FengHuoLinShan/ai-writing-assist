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

function overrideRouterQuery(queryString, stateOverrides = {}) {
  const state = { currentProjectId: "p1", searchQuery: "", viewStates: {}, ...stateOverrides }
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

  it("倒置章节范围保留表单且不导航或检索，修正后可提交", async () => {
    overrideRouterQuery("")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    const router = (await import("../../../vue/bridge/index.js")).getRouter()
    await wrapper.find("#rag-search-input").setValue("旧塔")
    await wrapper.find("#rag-chapter-from").setValue("10")
    await wrapper.find("#rag-chapter-to").setValue("5")
    await wrapper.find('[data-action="do-search"]').trigger("click")

    expect(wrapper.find("#rag-chapter-range-error").text()).toBe("起始章不能大于结束章")
    expect(wrapper.find("#rag-chapter-from").element.value).toBe("10")
    expect(wrapper.find("#rag-chapter-to").element.value).toBe("5")
    expect(wrapper.find("#rag-chapter-from").attributes("aria-invalid")).toBe("true")
    expect(wrapper.find("#rag-chapter-to").attributes("aria-describedby")).toBe("rag-chapter-range-error")
    expect(globalThis.toast).toHaveBeenCalledWith("起始章不能大于结束章", "warning")
    expect(router.navigate).not.toHaveBeenCalled()
    expect(globalThis.api.context.searchEvidence).not.toHaveBeenCalled()

    await wrapper.find("#rag-chapter-to").setValue("10")
    await wrapper.find('[data-action="do-search"]').trigger("click")
    expect(wrapper.find("#rag-chapter-range-error").exists()).toBe(false)
    expect(wrapper.find("#rag-chapter-from").attributes("aria-invalid")).toBeUndefined()
    expect(router.navigate).toHaveBeenCalledWith("rag", "search", true, expect.any(URLSearchParams))
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

  it("倒置章节范围的深链保持可修正且不自动检索或改写 URL", async () => {
    const query = "q=%E6%97%A7%E5%A1%94&chapter_from=10&chapter_to=5"
    overrideRouterQuery(query)
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    const router = (await import("../../../vue/bridge/index.js")).getRouter()
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(wrapper.find("#rag-search-input").element.value).toBe("旧塔")
    expect(wrapper.find("#rag-chapter-from").element.value).toBe("10")
    expect(wrapper.find("#rag-chapter-to").element.value).toBe("5")
    expect(wrapper.find("#rag-chapter-range-error").text()).toBe("起始章不能大于结束章")
    expect(globalThis.toast).toHaveBeenCalledWith("起始章不能大于结束章", "warning")
    expect(globalThis.api.context.searchEvidence).not.toHaveBeenCalled()
    expect(router.navigate).not.toHaveBeenCalled()
  })

  it("格式错误的章节深链展开筛选并保留给作者修正", async () => {
    const query = "q=%E6%97%A7%E5%A1%94&chapter_from=2.5"
    overrideRouterQuery(query)
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    const router = (await import("../../../vue/bridge/index.js")).getRouter()
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(wrapper.find(".rag-advanced-filters").attributes("open")).toBeDefined()
    expect(wrapper.find("#rag-search-input").element.value).toBe("旧塔")
    expect(wrapper.find("#rag-chapter-from").element.value).toBe("2.5")
    expect(wrapper.find("#rag-chapter-range-error").text()).toBe("起始章必须是大于等于 1 的整数")
    expect(globalThis.toast).toHaveBeenCalledWith("起始章必须是大于等于 1 的整数", "warning")
    expect(globalThis.api.context.searchEvidence).not.toHaveBeenCalled()
    expect(router.navigate).not.toHaveBeenCalled()

    await wrapper.find("#rag-chapter-from").setValue("2")
    await wrapper.find('[data-action="do-search"]').trigger("click")
    expect(wrapper.find("#rag-chapter-range-error").exists()).toBe(false)
    expect(router.navigate).toHaveBeenCalledWith("rag", "search", true, expect.any(URLSearchParams))
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
  it("卡片直接展示父 Scene 与当前创作关系并可跳转", async () => {
    overrideRouterQuery(
      "q=铜铃&kind=smart&content_mode=canonical&visibility=author&scope=manuscript",
      { viewStates: { writing: { projectId: "p1", currentSceneId: "scene-12" } } },
    )
    globalThis.api.context.searchEvidence = vi.fn(async () => ({
      total: 1,
      warnings: [],
      degraded: false,
      hits: [{
        kind: "manuscript",
        title: "第十一章",
        snippet: "林晚在旧塔找到铜铃。",
        chapter_index: 11,
        source_ref: { content_mode: "canonical", chapter_index: 11, version_number: 1 },
        scene_refs: [{
          target_type: "outline_scene",
          target_id: "scene-11",
          scene_index: 11,
          scene_title: "旧塔铜铃",
          context_summary: "目标：确认密道入口；冲突：铜铃声会惊动守卫",
        }],
        parent_scene_contexts: [{
          target_type: "outline_scene",
          target_id: "scene-10",
          scene_index: 10,
          scene_title: "进入旧塔",
          context_summary: "目标：找到旧塔入口",
        }, {
          target_type: "outline_scene",
          target_id: "scene-11",
          scene_index: 11,
          scene_title: "旧塔铜铃",
          context_summary: "目标：确认密道入口；冲突：铜铃声会惊动守卫",
        }],
        writing_relevance: {
          kind: "previous_scene",
          label: "前序 Scene：可用于核对当前 Scene 的剧情承接。",
        },
      }],
    }))

    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    await vi.waitFor(() => expect(wrapper.find(".rag-result-context").exists()).toBe(true))

    expect(wrapper.find(".rag-result-context").text()).toContain("Scene 11 · 旧塔铜铃")
    expect(wrapper.find(".rag-result-context").text()).toContain("Scene 10 · 进入旧塔")
    expect(wrapper.findAll(".rag-result-context__summary")).toHaveLength(2)
    expect(wrapper.find(".rag-result-context").text()).toContain("剧情承接")
    expect(wrapper.find(".rag-result-evidence-label").text()).toBe("命中依据")
    expect(globalThis.api.context.searchEvidence).toHaveBeenCalledWith(
      expect.objectContaining({ context_scene_id: "scene-12" }),
      expect.any(Object),
    )

    await wrapper.findAll('[data-action="open-scene-context"]')[1].trigger("click")
    const router = (await import("../../../vue/bridge/index.js")).getRouter()
    expect(router.navigate).toHaveBeenCalledWith("scene", "scene-11")
  })

  it("读者视角不把被省略的作者 Scene 元数据误报为未映射", async () => {
    overrideRouterQuery("q=铜铃&kind=smart&content_mode=canonical&visibility=reader&cutoff_chapter=11&scope=manuscript")
    globalThis.api.context.searchEvidence = vi.fn(async () => ({
      total: 1,
      warnings: [],
      degraded: false,
      hits: [{
        kind: "manuscript",
        title: "第十一章",
        snippet: "铜铃响起。",
        chapter_index: 11,
        source_ref: { content_mode: "canonical", chapter_index: 11, version_number: 1 },
        scene_refs: [{ target_type: "outline_scene", target_id: "scene-11" }],
        writing_relevance: {},
      }],
    }))

    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    await vi.waitFor(() => expect(wrapper.find(".rag-result-card").exists()).toBe(true))
    expect(wrapper.find(".rag-result-context").exists()).toBe(false)
    expect(wrapper.text()).not.toContain("未关联 Scene")
  })

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
