/**
 * RagSearchView 组件测试 — 表单初始化、提交、路由恢复（对应原 ragView.test.js
 * 的路由恢复 round-trip 用例）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { nextTick } from "vue"

const confirmAiReference = vi.hoisted(() => vi.fn())
vi.mock("../../../shared/aiReferenceModal.js", () => ({ confirmAiReference }))

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

function makeAskWorldResult(overrides = {}) {
  return {
    question: "旧塔铜铃来自哪里",
    answer: "现有证据显示，铜铃来自旧塔守卫室。",
    claims: [{ text: "铜铃来自旧塔守卫室。", citation_keys: ["page:source"] }],
    uncertainty: "当前只找到一页直接来源。",
    no_answer: false,
    citations: [{
      citation_key: "page:source",
      kind: "world_bible_page",
      title: "旧塔守卫",
      snippet: "铜铃存放在旧塔守卫室。",
      source_hash: "a".repeat(64),
      source_version: 3,
      page_id: "page-1",
    }],
    response_hash: "b".repeat(64),
    evidence_trace: {
      included_titles: ["旧塔守卫"],
      excluded_count: 1,
      truncated_titles: [],
      warnings: [],
      degraded: false,
      checks_run: ["作者可见性与项目隔离"],
      not_run: ["工作稿", "角色视角问答"],
    },
    model: "internal-model-name",
    provider: "internal-provider",
    context_snapshot_id: "internal-snapshot-id",
    ...overrides,
  }
}

function overrideRouterQuery(queryString, stateOverrides = {}) {
  const state = { currentProjectId: "p1", searchQuery: "", viewStates: {}, ...stateOverrides }
  setBridgeOverrides({
    state,
    router: {
      ...globalThis.router,
      getCurrentQuery: () => new URLSearchParams(queryString),
      navigate: vi.fn(async () => true),
      commitCurrentQuery: vi.fn(() => true),
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  confirmAiReference.mockResolvedValue({ id: "confirm-default" })
  resetRagSearchSession()
  globalThis.api.context.searchEvidence = vi.fn(async () => ({
    total: 3,
    hits: makeHits(3),
    warnings: [],
    degraded: false,
  }))
  globalThis.api.generate.askWorld = vi.fn(async () => makeAskWorldResult())
  globalThis.api.generate.openAskWorldCitation = vi.fn(async () => ({
    status: "current",
    kind: "world_bible_page",
    title: "旧塔守卫",
    text: "铜铃存放在旧塔守卫室。",
    page_id: "page-1",
    warnings: [],
  }))
  globalThis.api.generate.saveAskWorldSuggestion = vi.fn(async () => ({
    suggestion: { status: "pending" },
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

  it("外部不同 query 覆盖旧路由的未提交表单", () => {
    ragSearchSession.formRouteSignature = new URLSearchParams("q=旧塔").toString()
    ragSearchSession.formState = {
      query: "未提交草稿",
      searchKind: "literal",
      contentMode: "working",
      scopes: ["manuscript"],
    }
    overrideRouterQuery("q=新塔&kind=smart&content_mode=canonical&scope=world")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })

    expect(wrapper.find("#rag-search-input").element.value).toBe("新塔")
    expect(wrapper.find("#rag-search-kind").element.value).toBe("smart")
    expect(wrapper.find("#rag-content-mode").element.value).toBe("canonical")
  })

  it("路由含高级筛选时摘要展开", () => {
    overrideRouterQuery("q=旧塔&chapter_from=2&chapter_to=5")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    expect(wrapper.find(".rag-advanced-filters").attributes("open")).toBeDefined()
    expect(wrapper.find('[data-role="rag-advanced-summary"]').text()).toContain("第 2–5 章")
  })

  it("主查询和常用条件有可见标签与说明", () => {
    overrideRouterQuery("")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })

    expect(wrapper.get("form.novel-search-panel").exists()).toBe(true)
    expect(wrapper.get('label[for="rag-search-input"]').text()).toContain("想查什么")
    expect(wrapper.get("#rag-search-kind").attributes("aria-describedby")).toBe("rag-search-kind-help")
    expect(wrapper.get("#rag-content-mode").attributes("aria-describedby")).toBe("rag-content-mode-help")
    expect(wrapper.get('[data-role="rag-advanced-summary"]').text()).toBe("视角、章节和资料范围")
    expect(wrapper.get("#rag-include-pending").attributes("disabled")).toBeDefined()
    expect(wrapper.get("#rag-include-pending-help").text()).toContain("先勾选“世界设定”")
  })

  it("字面搜索锁定正文范围并解释原因", async () => {
    overrideRouterQuery("")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    await wrapper.get('[data-search-scope="world"]').setValue(true)
    await wrapper.get("#rag-include-pending").setValue(true)
    await wrapper.get("#rag-search-kind").setValue("literal")

    expect(wrapper.get('[data-search-scope="world"]').attributes("disabled")).toBeDefined()
    expect(wrapper.get('[data-search-scope="outline"]').attributes("disabled")).toBeDefined()
    expect(wrapper.get("#rag-include-pending").element.checked).toBe(false)
    expect(wrapper.text()).toContain("字面搜索只查正文")
  })
})

describe("提交", () => {
  it("新检索条件就地更新 URL 并搜索，不重挂页面", async () => {
    overrideRouterQuery("")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    const input = wrapper.find("#rag-search-input")
    await input.setValue("旧塔")
    const originalInput = input.element
    await wrapper.get("form.novel-search-panel").trigger("submit")

    const router = (await import("../../../vue/bridge/index.js")).getRouter()
    expect(router.navigate).not.toHaveBeenCalled()
    expect(router.commitCurrentQuery).toHaveBeenCalledWith(expect.any(URLSearchParams), "push")
    const route = router.commitCurrentQuery.mock.calls[0][0]
    expect(route.get("q")).toBe("旧塔")
    expect(route.get("kind")).toBe("smart")
    await vi.waitFor(() => expect(globalThis.api.context.searchEvidence).toHaveBeenCalled())
    expect(wrapper.find("#rag-search-input").element).toBe(originalInput)
    await wrapper.find("#rag-search-input").setValue("旧塔旁的钟")
    expect(ragSearchSession.formRouteSignature).toBe(route.toString())
  })

  it("嵌入 AI 工具时保留外层页面和抽屉路由状态", async () => {
    overrideRouterQuery("owner_ai=1&owner_ai_mode=evidence&chapter_index=2")
    const wrapper = mount(RagSearchView, {
      props: { projectId: "p1", characters: [], scenes: [], embedded: true },
    })
    await wrapper.get("#rag-search-input").setValue("旧塔")
    await wrapper.get("form.novel-search-panel").trigger("submit")

    const router = (await import("../../../vue/bridge/index.js")).getRouter()
    const route = router.commitCurrentQuery.mock.calls.at(-1)[0]
    expect(route.get("owner_ai")).toBe("1")
    expect(route.get("owner_ai_mode")).toBe("evidence")
    expect(route.get("chapter_index")).toBe("2")
    expect(route.get("q")).toBe("旧塔")
    await vi.waitFor(() => expect(globalThis.api.context.searchEvidence).toHaveBeenCalled())
  })

  it("签名未变时本地直接搜索，不重复导航", async () => {
    overrideRouterQuery("q=旧塔&kind=smart&content_mode=canonical&visibility=author&scope=manuscript")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    // 挂载时恢复已执行一次搜索，清空调用记录再提交相同条件
    await vi.waitFor(() => expect(globalThis.api.context.searchEvidence).toHaveBeenCalled())
    globalThis.api.context.searchEvidence.mockClear()

    const router = (await import("../../../vue/bridge/index.js")).getRouter()
    await wrapper.get("form.novel-search-panel").trigger("submit")
    await vi.waitFor(() => expect(globalThis.api.context.searchEvidence).toHaveBeenCalled())
    expect(router.navigate).not.toHaveBeenCalled()
  })

  it("校验失败仅警告不搜索", async () => {
    overrideRouterQuery("")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    await wrapper.find("#rag-search-input").setValue("旧塔")
    await wrapper.find("#rag-visibility-mode").setValue("reader")
    await wrapper.get("form.novel-search-panel").trigger("submit")
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
    await wrapper.get("form.novel-search-panel").trigger("submit")

    expect(wrapper.find("#rag-chapter-range-error").text()).toBe("起始章不能大于结束章")
    expect(wrapper.find("#rag-chapter-from").element.value).toBe("10")
    expect(wrapper.find("#rag-chapter-to").element.value).toBe("5")
    expect(wrapper.find("#rag-chapter-from").attributes("aria-invalid")).toBe("true")
    expect(wrapper.find("#rag-chapter-to").attributes("aria-describedby")).toBe("rag-chapter-range-error")
    expect(globalThis.toast).toHaveBeenCalledWith("起始章不能大于结束章", "warning")
    expect(router.navigate).not.toHaveBeenCalled()
    expect(globalThis.api.context.searchEvidence).not.toHaveBeenCalled()

    await wrapper.find("#rag-chapter-to").setValue("10")
    await wrapper.get("form.novel-search-panel").trigger("submit")
    expect(wrapper.find("#rag-chapter-range-error").exists()).toBe(false)
    expect(wrapper.find("#rag-chapter-from").attributes("aria-invalid")).toBeUndefined()
    expect(router.commitCurrentQuery).toHaveBeenCalledWith(expect.any(URLSearchParams), "push")
    expect(router.navigate).not.toHaveBeenCalled()
  })
})

describe("问世界", () => {
  it("按作者可见正式资料回答、显示可打开引用且隐藏内部字段", async () => {
    overrideRouterQuery("")
    const wrapper = mount(RagSearchView, {
      props: { projectId: "p1", characters: [], scenes: [] },
    })
    await wrapper.find("#rag-search-input").setValue("旧塔铜铃来自哪里")
    await wrapper.find('[data-action="ask-world"]').trigger("click")

    await vi.waitFor(() => expect(wrapper.find(".ask-world-answer").exists()).toBe(true))
    expect(globalThis.api.generate.askWorld).toHaveBeenCalledWith(
      { novel_id: "p1", question: "旧塔铜铃来自哪里", context_confirmation_id: "confirm-default" },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(wrapper.text()).toContain("铜铃来自旧塔守卫室")
    expect(wrapper.text()).toContain("查看来源：旧塔守卫")
    expect(wrapper.text()).toContain("本次未查：工作稿、角色视角问答")
    expect(wrapper.text()).not.toContain("internal-model-name")
    expect(wrapper.text()).not.toContain("internal-provider")
    expect(wrapper.text()).not.toContain("internal-snapshot-id")
    expect(wrapper.text()).not.toContain("b".repeat(64))

    await wrapper.find('[data-action="open-ask-world-citation"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find(".ask-world-source__text").exists()).toBe(true))
    expect(wrapper.find(".ask-world-source__text").text()).toContain("铜铃存放在旧塔守卫室")
    const pageLink = wrapper.get('[data-action="open-ask-world-page"]')
    expect(pageLink.attributes()).toMatchObject({
      href: "#workbench/p1/world/bible?page_id=page-1",
      target: "_blank",
      rel: "noopener",
    })
    expect(pageLink.text()).toContain("新标签页")
  })

  it("只有作者明确保存时才创建待处理建议", async () => {
    overrideRouterQuery("")
    const wrapper = mount(RagSearchView, {
      props: { projectId: "p1", characters: [], scenes: [] },
    })
    await wrapper.find("#rag-search-input").setValue("旧塔铜铃来自哪里")
    await wrapper.find('[data-action="ask-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-action="save-ask-world-answer"]').exists()).toBe(true))
    expect(globalThis.api.generate.saveAskWorldSuggestion).not.toHaveBeenCalled()

    await wrapper.find('[data-action="save-ask-world-answer"]').trigger("click")
    await vi.waitFor(() => expect(globalThis.api.generate.saveAskWorldSuggestion).toHaveBeenCalled())
    expect(globalThis.api.generate.saveAskWorldSuggestion).toHaveBeenCalledWith(
      expect.objectContaining({
        novel_id: "p1",
        question: "旧塔铜铃来自哪里",
        response_hash: "b".repeat(64),
      }),
    )
    expect(wrapper.text()).toContain("已进入待处理，不会直接改写正式设定")
    expect(globalThis.toast).toHaveBeenCalledWith(
      "已保存为待处理世界笔记建议，不会直接改写正式设定。",
      "success",
    )

    await wrapper.find('[data-action="open-ask-world-suggestions"]').trigger("click")
    const router = (await import("../../../vue/bridge/index.js")).getRouter()
    expect(router.navigate.mock.calls.at(-1)[0]).toBe("world")
    expect(router.navigate.mock.calls.at(-1)[1]).toBe("bible")
    expect(router.navigate.mock.calls.at(-1)[3].get("open")).toBe("suggestions")
  })

  it("证据不足时明确拒答且不能保存", async () => {
    overrideRouterQuery("")
    globalThis.api.generate.askWorld = vi.fn(async () => makeAskWorldResult({
      answer: "当前可回读的项目证据不足，无法可靠回答。",
      claims: [],
      citations: [],
      no_answer: true,
    }))
    const wrapper = mount(RagSearchView, {
      props: { projectId: "p1", characters: [], scenes: [] },
    })
    await wrapper.find("#rag-search-input").setValue("月海有几颗卫星")
    await wrapper.find('[data-action="ask-world"]').trigger("click")

    await vi.waitFor(() => expect(wrapper.text()).toContain("证据不足"))
    expect(wrapper.find('[data-action="save-ask-world-answer"]').exists()).toBe(false)
    expect(globalThis.api.generate.saveAskWorldSuggestion).not.toHaveBeenCalled()
  })

  it("停止后保留诚实终态，切换项目不会接收迟到回答", async () => {
    overrideRouterQuery("")
    let resolveRequest
    let signal
    globalThis.api.generate.askWorld = vi.fn((_payload, options) => {
      signal = options.signal
      return new Promise((resolve, reject) => {
        resolveRequest = resolve
        signal.addEventListener("abort", () => {
          const error = new Error("aborted")
          error.name = "AbortError"
          reject(error)
        })
      })
    })
    const wrapper = mount(RagSearchView, {
      props: { projectId: "p1", characters: [], scenes: [] },
    })
    await wrapper.find("#rag-search-input").setValue("旧塔铜铃来自哪里")
    await wrapper.find('[data-action="ask-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-action="stop-ask-world"]').exists()).toBe(true))
    expect(wrapper.get('[data-action="ask-world"]').attributes("disabled")).toBeDefined()
    expect(wrapper.get('[data-action="ask-world"]').text()).toBe("问答中…")
    expect(globalThis.api.generate.askWorld).toHaveBeenCalledTimes(1)
    await wrapper.find('[data-action="stop-ask-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.text()).toContain("远端请求可能仍在结束"))
    expect(signal.aborted).toBe(true)

    globalThis.api.generate.askWorld = vi.fn(() => new Promise((resolve) => {
      resolveRequest = resolve
    }))
    await wrapper.find('[data-action="ask-world"]').trigger("click")
    await wrapper.setProps({ projectId: "p2" })
    resolveRequest(makeAskWorldResult({ answer: "不应显示的迟到回答" }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(wrapper.text()).not.toContain("不应显示的迟到回答")
  })

  it("离开页面后丢弃迟到的问答", async () => {
    overrideRouterQuery("")
    let resolveAsk
    globalThis.api.generate.askWorld = vi.fn((_payload, options) => new Promise((resolve) => {
      resolveAsk = resolve
      // 模拟远端已开始、无法被本地 abort 立刻中断。
      expect(options.signal).toBeInstanceOf(AbortSignal)
    }))
    const wrapper = mount(RagSearchView, {
      props: { projectId: "p1", characters: [], scenes: [] },
    })
    await wrapper.find("#rag-search-input").setValue("旧塔铜铃来自哪里")
    await wrapper.find('[data-action="ask-world"]').trigger("click")
    await vi.waitFor(() => expect(globalThis.api.generate.askWorld).toHaveBeenCalledOnce())
    const signal = globalThis.api.generate.askWorld.mock.calls[0][1].signal

    wrapper.unmount()
    expect(signal.aborted).toBe(true)
    resolveAsk(makeAskWorldResult({ answer: "不应回写的迟到回答" }))
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(globalThis.toast).not.toHaveBeenCalledWith(expect.stringContaining("迟到回答"), expect.anything())
  })

  it("停止后即使远端仍成功返回也丢弃同项目迟到回答", async () => {
    overrideRouterQuery("")
    let resolveAsk
    globalThis.api.generate.askWorld = vi.fn((_payload, options) => new Promise((resolve) => {
      resolveAsk = resolve
      expect(options.signal).toBeInstanceOf(AbortSignal)
    }))
    const wrapper = mount(RagSearchView, {
      props: { projectId: "p1", characters: [], scenes: [] },
    })
    await wrapper.find("#rag-search-input").setValue("旧塔铜铃来自哪里")
    await wrapper.find('[data-action="ask-world"]').trigger("click")
    await vi.waitFor(() => expect(globalThis.api.generate.askWorld).toHaveBeenCalledOnce())

    await wrapper.find('[data-action="stop-ask-world"]').trigger("click")
    expect(globalThis.api.generate.askWorld.mock.calls[0][1].signal.aborted).toBe(true)
    expect(wrapper.find('[data-action="stop-ask-world"]').exists()).toBe(false)
    resolveAsk(makeAskWorldResult({ answer: "不应显示的同项目迟到回答" }))
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(wrapper.text()).toContain("远端请求可能仍在结束")
    expect(wrapper.text()).not.toContain("不应显示的同项目迟到回答")
  })

  it("离开页面后不显示迟到的引用或保存错误", async () => {
    overrideRouterQuery("")
    let rejectCitation
    let rejectSave
    globalThis.api.generate.openAskWorldCitation = vi.fn(() => new Promise((_resolve, reject) => {
      rejectCitation = reject
    }))
    globalThis.api.generate.saveAskWorldSuggestion = vi.fn(() => new Promise((_resolve, reject) => {
      rejectSave = reject
    }))
    const wrapper = mount(RagSearchView, {
      props: { projectId: "p1", characters: [], scenes: [] },
    })
    await wrapper.find("#rag-search-input").setValue("旧塔铜铃来自哪里")
    await wrapper.find('[data-action="ask-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-action="save-ask-world-answer"]').exists()).toBe(true))

    await wrapper.find('[data-action="open-ask-world-citation"]').trigger("click")
    await wrapper.find('[data-action="save-ask-world-answer"]').trigger("click")
    wrapper.unmount()
    rejectCitation(new Error("迟到的引用失败"))
    rejectSave(new Error("迟到的保存失败"))
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(globalThis.toast).not.toHaveBeenCalledWith("来源打开失败，请稍后重试", "error")
    expect(globalThis.toast).not.toHaveBeenCalledWith("保存失败，回答仍保留在当前页面。", "error")
  })
})

describe("路由恢复", () => {
  it("检索期间保留稳定骨架并播报状态", async () => {
    let resolveSearch
    globalThis.api.context.searchEvidence = vi.fn(() => new Promise((resolve) => {
      resolveSearch = resolve
    }))
    overrideRouterQuery("q=旧塔&kind=smart&content_mode=canonical&visibility=author&scope=manuscript")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })

    await vi.waitFor(() => expect(globalThis.api.context.searchEvidence).toHaveBeenCalled())
    expect(wrapper.find(".loading-skeleton").attributes("role")).toBe("status")
    expect(wrapper.find("#rag-results").attributes("aria-busy")).toBe("true")
    expect(wrapper.find(".sr-only").text()).toContain("正在查找作品资料")
    expect(wrapper.get('[data-action="do-search"]').attributes("disabled")).toBeDefined()
    expect(wrapper.get('[data-action="do-search"]').text()).toBe("查找中…")

    resolveSearch({ total: 0, hits: [], warnings: [], degraded: false })
    await vi.waitFor(() => expect(wrapper.find("#rag-results").attributes("aria-busy")).toBeUndefined())
  })

  it("挂载时按路由恢复并渲染结果", async () => {
    overrideRouterQuery("q=旧塔&kind=smart&content_mode=canonical&visibility=author&scope=manuscript")
    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    await vi.waitFor(() => {
      expect(wrapper.findAll(".rag-result-card")).toHaveLength(3)
    })
    expect(wrapper.find(".rag-result-count").text()).toContain("找到 3")
    expect(wrapper.find(".rag-result-score").exists()).toBe(false)
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
    await wrapper.get("form.novel-search-panel").trigger("submit")
    expect(wrapper.find("#rag-chapter-range-error").exists()).toBe(false)
    expect(router.commitCurrentQuery).toHaveBeenCalledWith(expect.any(URLSearchParams), "push")
    expect(router.navigate).not.toHaveBeenCalled()
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
    expect(wrapper.find(".rag-search-empty").text()).toContain("输入人物、地点、事件或原文片段")
  })
})

describe("结果交互", () => {
  it("无结果时给出下一步并可就地换用字面搜索", async () => {
    overrideRouterQuery("q=旧塔&kind=smart&content_mode=canonical&visibility=author&scope=manuscript")
    globalThis.api.context.searchEvidence = vi.fn(async () => ({
      total: 0,
      hits: [],
      warnings: [],
      degraded: false,
    }))
    globalThis.api.context.grepEvidence = vi.fn(async () => ({
      total: 0,
      hits: [],
      warnings: [],
      degraded: false,
    }))

    const wrapper = mount(RagSearchView, { props: { projectId: "p1", characters: [], scenes: [] } })
    await vi.waitFor(() => expect(wrapper.get(".rag-results-empty h2").text()).toBe("没有找到匹配资料"))
    expect(wrapper.find(".rag-results-empty").text()).toContain("试试缩短关键词")

    await wrapper.get('[data-action="retry-literal-search"]').trigger("click")
    await vi.waitFor(() => expect(globalThis.api.context.grepEvidence).toHaveBeenCalled())
  })

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
        score: 0.91,
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

    expect(wrapper.find(".rag-result-context").text()).toContain("场景 11 · 旧塔铜铃")
    expect(wrapper.find(".rag-result-context").text()).toContain("场景 10 · 进入旧塔")
    expect(wrapper.findAll(".rag-result-context__summary")).toHaveLength(2)
    expect(wrapper.find(".rag-result-context").text()).toContain("剧情承接")
    expect(wrapper.find(".rag-result-evidence-label").text()).toBe("匹配内容")
    expect(wrapper.find(".rag-result-score").text()).toContain("匹配度91%")
    expect(wrapper.find(".rag-result-score-help").text()).toBe("匹配度仅用于本次结果排序")
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
      expect(document.getElementById("rag-evidence-drawer")?.textContent).toContain("旧塔的铜铃在夜里响起")
    })
    expect(document.querySelector("#rag-evidence-drawer mark")?.textContent).toBe("铜铃")
    expect(document.getElementById("rag-evidence-drawer")?.getAttribute("role")).toBe("dialog")

    document.querySelector('[data-action="close-drawer"]')?.click()
    await nextTick()
    expect(document.getElementById("rag-evidence-drawer")).toBeNull()
  })
})
