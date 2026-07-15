import { describe, it, expect, vi, beforeEach } from "vitest"
import ragView from "../views/ragView.js"
import { resetState, clearDocument } from "./helpers.js"

beforeEach(() => {
  resetState()
  clearDocument()
  localStorage.clear()
  if (ragView._rebuildPoller?.stop) ragView._rebuildPoller.stop()
  ragView._apiAvailable = true
  ragView._loading = false
  ragView._totalChunks = 0
  ragView._embeddingFailedCount = 0
  ragView._statusDegraded = false
  ragView._statusWarnings = []
  ragView._statusItems = []
  ragView._embeddingRuntime = { started: false, healthy: false, cache_stats: {} }
  ragView._metrics = null
  ragView._retryableEmbeddingCount = 0
  ragView._prewarmState = "idle"
  ragView._prewarmWarning = ""
  ragView._rebuildPoller = null
  ragView._rebuildProgress = null
  ragView._rebuildInfo = null
  ragView._indexFreshness = {}
  ragView._characters = []
  ragView._scenes = []
  ragView._cancelActiveSearch()
  ragView._cancelActiveDrawer()
  ragView._searchHits = []
  ragView._searchVisibleCount = 0
  ragView._searchTotal = 0
  ragView._searchResultMeta = null
  ragView._searchQuery = ""
  ragView._searchGeneration = 0
  ragView._lastExecutedRouteSignature = ""
  ragView._lastSearchPayload = null
  ragView._evidenceHealth = null
  ragView._retrievalTraces = []
  ragView._retrievalTracesState = "idle"
  ragView._retrievalTracesError = ""
  ragView._taskRetryPending = false
  api.context.searchEvidence = vi.fn()
  api.context.grepEvidence = vi.fn()
  api.context.readEvidence = vi.fn()
  api.context.inspectEvidence = vi.fn()
  api.context.traceEvidence = vi.fn()
  vi.clearAllMocks()
  router.getCurrentQuery.mockReturnValue(new URLSearchParams())
  router.navigate.mockResolvedValue(true)
})

describe("ragView", () => {
  it("按后端分页上限加载全部角色筛选项", async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) => ({
      id: `character-${index + 1}`,
      name: `角色 ${index + 1}`,
    }))
    api.world.listCharacters
      .mockResolvedValueOnce({ items: firstPage, total: 51 })
      .mockResolvedValueOnce({
        items: [{ id: "character-51", name: "角色 51" }],
        total: 51,
      })

    const characters = await ragView._loadAllCharacters("p1")

    expect(api.world.listCharacters.mock.calls).toEqual([
      [{ novel_id: "p1", skip: 0, limit: 50 }],
      [{ novel_id: "p1", skip: 50, limit: 50 }],
    ])
    expect(characters).toHaveLength(51)
  })

  describe("ragView render", () => {
    it("为检索与索引范围字段提供程序化标签", async () => {
      state.currentSubView = "search"
      document.body.innerHTML = await ragView.render()
      expect(document.getElementById("rag-search-input").getAttribute("aria-label")).toBe("检索关键词")

      state.currentSubView = "status"
      document.body.innerHTML = await ragView.render()
      expect(document.getElementById("rag-rebuild-content-mode").labels[0].textContent).toContain("正文版本")
      expect(document.getElementById("rag-rebuild-start").labels[0].textContent).toContain("起始章节")
      expect(document.getElementById("rag-rebuild-end").labels[0].textContent).toContain("结束章节")
    })

    it("将页面定位为作者资料查找并默认收起高级筛选", async () => {
      state.currentSubView = "search"
      document.body.innerHTML = await ragView.render()

      expect(document.body.textContent).toContain("查找小说资料")
      expect(document.body.textContent).toContain("为当前创作核对事实")
      const advanced = document.querySelector('[data-role="rag-advanced-filters"]')
      expect(advanced.open).toBe(false)
      expect(advanced.querySelector("#rag-visibility-mode")).not.toBeNull()
      expect(advanced.querySelector("#rag-chapter-from")).not.toBeNull()
      expect(advanced.querySelector('[data-search-scope="world"]')).not.toBeNull()
      expect(advanced.querySelector("#rag-search-kind")).toBeNull()
      expect(document.getElementById("rag-search-kind")).not.toBeNull()
    })

    it("路由带高级条件时自动展开并显示作者可读摘要", async () => {
      router.getCurrentQuery.mockReturnValue(new URLSearchParams([
        ["visibility", "reader"],
        ["chapter_from", "2"],
        ["chapter_to", "9"],
        ["cutoff_chapter", "8"],
        ["scope", "manuscript"],
        ["scope", "world"],
        ["include_pending", "1"],
      ]))
      state.currentSubView = "search"
      document.body.innerHTML = await ragView.render()

      const advanced = document.querySelector('[data-role="rag-advanced-filters"]')
      const summary = document.querySelector('[data-role="rag-advanced-summary"]')
      expect(advanced.open).toBe(true)
      expect(summary.textContent).toContain("第 2–9 章")
      expect(summary.textContent).toContain("读者视角")
      expect(summary.textContent).toContain("可见至第 8 章")
      expect(summary.textContent).toContain("范围：正文、世界对象")
      expect(summary.textContent).toContain("含待处理对象")
      expect(summary.textContent).not.toContain("scene-")
    })

    it.each([
      {
        name: "status 子视图展示创作证据健康",
        subView: "status",
        setup: () => {
          ragView._evidenceHealth = {
            health_state: "degraded",
            health_reasons: ["eligible_mapping_below_target"],
            scene_span_coverage: { precise_span_rate: 0.91 },
            rag_mapping_coverage: { eligible_mapping_rate: 0.82 },
            retrieval_summary: { query_count: 12, empty_count: 3 },
          }
        },
        expected: ["创作证据健康", "需要处理", "91%", "82%", "12"],
      },
      {
        name: "status 子视图显示维度、worker 和 metrics 诊断",
        subView: "status",
        setup: () => {
          ragView._totalChunks = 26
          ragView._embeddingDim = 768
          ragView._configuredEmbeddingDim = 1024
          ragView._indexedEmbeddingDim = 768
          ragView._embeddingDimensionMismatch = true
          ragView._embeddingRuntime = { started: true, healthy: true, cache_stats: { hits: 3, misses: 2 } }
          ragView._metrics = { avg_latency_ms: 123.4, embedding_avg_ms: 50, degraded_rate: 0.25 }
          ragView._retryableEmbeddingCount = 2
        },
        expected: ["技术诊断详情", "实际维度", "768", "配置维度", "1024", "ready", "123.4ms", "重试失败向量"],
      },
      {
        name: "status 子视图包含索引状态",
        subView: "status",
        setup: () => {},
        expected: ["索引维护"],
      },
      {
        name: "status 子视图显示索引降级提示",
        subView: "status",
        setup: () => {
          ragView._totalChunks = 8
          ragView._embeddingFailedCount = 2
          ragView._statusDegraded = true
          ragView._statusWarnings = ["有 2 个片段 embedding 失败，检索和抽取可能不准确"]
        },
        expected: ["索引不完整", "降级片段"],
      },
      {
        name: "search 子视图包含搜索框",
        subView: "search",
        setup: () => {},
        expected: ["检索方式", "字面搜索", "可见视角", "按语义相关性查找", "聚合显示"],
      },
      {
        name: "status 子视图展示最近片段列表",
        subView: "status",
        setup: () => {
          ragView._totalChunks = 2
          ragView._statusItems = [
            {
              chunk_index: 0, chapter_index: 1, char_count: 88, embedding_status: "success",
              entity_ids: ["e1"], character_ids: ["c1", "c2"], thread_ids: [], scene_id: "s1",
              text: "铜铃在雨夜响起，旧档案缺页随风翻开。",
            },
            {
              chunk_index: 1, chapter_index: 1, char_count: 120, embedding_status: "failed",
              entity_ids: [], character_ids: [], thread_ids: ["t1"], scene_id: null,
              text: "a".repeat(200),
            },
          ]
        },
        expected: ["最近片段", "铜铃在雨夜响起", "a".repeat(120) + "..."],
        assertRows: true,
      },
    ])("$name", async ({ subView, setup, expected, assertRows }) => {
      state.currentSubView = subView
      setup()
      const html = await ragView.render()
      if (assertRows) {
        document.body.innerHTML = html
        const rows = document.querySelectorAll("tbody tr")
        expect(rows.length).toBe(2)
        expect(rows[0].textContent).toContain("铜铃在雨夜响起")
        expect(rows[1].textContent).toContain("failed")
      }
      for (const text of expected) {
        expect(html).toContain(text)
      }
    })
  })

  describe("_doSearch", () => {
    it.each([
      {
        name: "渲染搜索结果到 DOM",
        projectId: "p1",
        query: "测试",
        body: '<div id="rag-results"></div>',
        response: { hits: [{ snippet: "测试结果", kind: "manuscript", score: 0.85 }] },
        expectedCall: "测试",
        expectedInHtml: ["测试结果"],
      },
      {
        name: "搜索降级时显示准确性提示",
        projectId: "p1",
        query: "测试",
        body: '<div id="rag-results"></div>',
        response: { degraded: true, warnings: ["embedding 生成失败，本次结果可能不准确"], hits: [{ snippet: "测试结果", kind: "manuscript", score: 0.5 }] },
        expectedInHtml: ["本次结果可能不准确", "测试结果"],
      },
      {
        name: "搜索结果为空时显示提示",
        projectId: null,
        query: "不存在",
        body: '<div id="rag-results"></div>',
        response: { hits: [] },
        expectedInHtml: ["未找到匹配结果"],
      },
      {
        name: "无结果容器时不操作",
        projectId: null,
        query: "test",
        body: "",
        response: { hits: [] },
        expectUndefined: true,
      },
    ])("$name", async ({ projectId, query, body, response, expectedCall, expectedInHtml, expectUndefined }) => {
      document.body.innerHTML = body
      if (projectId) state.currentProjectId = projectId
      api.context.searchEvidence.mockResolvedValue(response)

      const result = ragView._doSearch(query)
      if (expectUndefined) {
        await expect(result).resolves.toBeUndefined()
        return
      }
      await result
      if (expectedCall) {
        expect(api.context.searchEvidence).toHaveBeenCalledWith(
          expect.objectContaining({ query: expectedCall, content_mode: "canonical" }),
          expect.objectContaining({ signal: expect.any(AbortSignal) }),
        )
      }
      const results = document.getElementById("rag-results")
      for (const text of expectedInHtml) {
        expect(results?.textContent).toContain(text)
      }
    })

    it("超时保留查询和筛选并显示两种页内重试", async () => {
      state.currentProjectId = "p1"
      router.getCurrentQuery.mockReturnValue(new URLSearchParams([
        ["q", "安提哥努斯"],
        ["kind", "smart"],
        ["content_mode", "working"],
        ["visibility", "author"],
        ["scope", "manuscript"],
        ["chapter_from", "3"],
      ]))
      state.currentSubView = "search"
      document.body.innerHTML = await ragView.render()
      api.context.searchEvidence.mockRejectedValue(new Error("请求超时，请检查后端服务是否运行"))

      await ragView._doSearch("安提哥努斯")

      expect(document.getElementById("rag-search-input").value).toBe("安提哥努斯")
      expect(document.getElementById("rag-content-mode").value).toBe("working")
      expect(document.getElementById("rag-chapter-from").value).toBe("3")
      expect(document.getElementById("rag-results").textContent).toContain("暂时无法完成检索")
      expect(document.getElementById("rag-results").textContent).toContain("索引繁忙或连接暂时不可用")
      expect(document.getElementById("rag-results").textContent).not.toContain("后端服务是否运行")
      expect(document.getElementById("rag-results").textContent).not.toContain("未找到匹配结果")
      expect(document.querySelector('[data-action="retry-search"]')).not.toBeNull()
      expect(document.querySelector('[data-action="retry-literal-search"]')).not.toBeNull()
    })

    it("切换字面搜索重试时保留关键词与章节条件并更新路由", async () => {
      state.currentProjectId = "p1"
      router.getCurrentQuery.mockReturnValue(new URLSearchParams([
        ["q", "旧塔"],
        ["kind", "smart"],
        ["content_mode", "canonical"],
        ["visibility", "author"],
        ["scope", "manuscript"],
        ["chapter_from", "5"],
        ["chapter_to", "12"],
      ]))
      state.currentSubView = "search"
      document.body.innerHTML = await ragView.render()

      await ragView._retrySearch({ literal: true })

      const route = router.navigate.mock.calls.at(-1)[3]
      expect(route.get("q")).toBe("旧塔")
      expect(route.get("kind")).toBe("literal")
      expect(route.get("chapter_from")).toBe("5")
      expect(route.get("chapter_to")).toBe("12")
      expect(route.getAll("scope")).toEqual(["manuscript"])
    })

    it("原条件重试直接重新请求并替换错误卡", async () => {
      state.currentProjectId = "p1"
      const route = new URLSearchParams([
        ["q", "旧塔"],
        ["kind", "smart"],
        ["content_mode", "canonical"],
        ["visibility", "author"],
        ["scope", "manuscript"],
      ])
      router.getCurrentQuery.mockReturnValue(route)
      state.currentSubView = "search"
      document.body.innerHTML = await ragView.render()
      document.getElementById("rag-results").innerHTML = ragView._renderSearchError(new Error("timeout"))
      api.context.searchEvidence.mockResolvedValue({
        hits: [{ kind: "manuscript", title: "旧塔章节", snippet: "旧塔里的铜铃" }],
      })

      await ragView._retrySearch()

      expect(api.context.searchEvidence).toHaveBeenCalledTimes(1)
      expect(document.getElementById("rag-results").textContent).toContain("旧塔章节")
      expect(document.getElementById("rag-results").textContent).not.toContain("暂时无法完成检索")
    })
  })

  describe("渐进结果与路由恢复", () => {
    it("固定 58 条结果按 20 条渐进挂载且无重复丢失", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = '<div id="rag-results"></div>'
      api.context.searchEvidence.mockResolvedValue({
        total: 58,
        hits: Array.from({ length: 58 }, (_, index) => ({
          title: `结果 ${index + 1}`,
          snippet: `证据 ${index + 1}`,
          kind: "manuscript",
        })),
      })

      await ragView._doSearch("证据")
      expect(document.querySelectorAll(".rag-result-card")).toHaveLength(20)
      expect(document.querySelector(".rag-result-count")?.textContent).toContain("已显示 20")

      ragView._loadMoreSearchResults()
      expect(document.querySelectorAll(".rag-result-card")).toHaveLength(40)
      ragView._loadMoreSearchResults()

      const cards = [...document.querySelectorAll(".rag-result-card")]
      expect(cards).toHaveLength(58)
      expect(new Set(cards.map((card) => card.querySelector(".rag-result-title")?.textContent.trim())).size).toBe(58)
      expect(document.querySelector('[data-action="load-more-results"]')).toBeNull()
    })

    it("降级警告不计入首批 20 张结果卡", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = '<div id="rag-results"></div>'
      api.context.searchEvidence.mockResolvedValue({
        total: 20,
        degraded: true,
        warnings: ["关键词检索降级"],
        hits: Array.from({ length: 20 }, (_, index) => ({
          title: `结果 ${index + 1}`,
          snippet: `证据 ${index + 1}`,
          kind: "manuscript",
        })),
      })

      await ragView._doSearch("证据")

      expect(document.querySelectorAll(".rag-result-card")).toHaveLength(20)
      expect(document.querySelector(".rag-search-warning")?.textContent).toContain("关键词检索降级")
    })

    it("URL 条件可以恢复表单并 round-trip 为同一规范查询", async () => {
      const query = new URLSearchParams([
        ["q", "铜铃"],
        ["kind", "literal"],
        ["content_mode", "working"],
        ["visibility", "reader"],
        ["scope", "manuscript"],
        ["scope", "world"],
        ["chapter_from", "2"],
        ["chapter_to", "9"],
        ["cutoff_chapter", "8"],
        ["cutoff_offset", "12"],
        ["include_pending", "1"],
      ])
      router.getCurrentQuery.mockReturnValue(query)
      state.currentSubView = "search"
      document.body.innerHTML = await ragView.render()

      expect(document.getElementById("rag-search-input").value).toBe("铜铃")
      expect(document.getElementById("rag-search-kind").value).toBe("literal")
      expect(document.getElementById("rag-content-mode").value).toBe("working")
      expect(document.getElementById("rag-visibility-mode").value).toBe("reader")
      expect(document.getElementById("rag-chapter-from").value).toBe("2")
      expect(document.getElementById("rag-chapter-to").value).toBe("9")
      expect(document.querySelector('[data-search-scope="world"]').checked).toBe(true)
      expect(document.getElementById("rag-include-pending").checked).toBe(true)
      expect(ragView._searchRouteQuery("铜铃").toString()).toBe(query.toString())
    })

    it("新查询取消旧请求且晚到结果不能覆盖当前查询", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = '<div id="rag-results"></div>'
      const pending = []
      api.context.searchEvidence.mockImplementation((_payload, options) => (
        new Promise((resolve) => pending.push({ resolve, signal: options.signal }))
      ))

      const first = ragView._doSearch("旧查询")
      const second = ragView._doSearch("新查询")
      expect(pending[0].signal.aborted).toBe(true)

      pending[1].resolve({ hits: [{ title: "新结果", snippet: "新查询命中" }] })
      await second
      pending[0].resolve({ hits: [{ title: "旧结果", snippet: "不应出现" }] })
      await first

      expect(document.getElementById("rag-results").textContent).toContain("新结果")
      expect(document.getElementById("rag-results").textContent).not.toContain("旧结果")
    })

    it("空查询 URL 会清空签名并允许前进后重新检索同一关键词", async () => {
      state.currentProjectId = "p1"
      state.currentView = "rag"
      state.currentSubView = "search"
      const query = new URLSearchParams({ q: "旧塔" })
      router.getCurrentQuery.mockReturnValue(query)
      api.context.searchEvidence.mockResolvedValue({
        hits: [{ title: "旧塔结果", snippet: "旧塔证据", kind: "manuscript" }],
      })
      document.body.innerHTML = await ragView.render()
      ragView._restoreSearchFromRoute()
      await vi.waitFor(() => expect(api.context.searchEvidence).toHaveBeenCalledTimes(1))

      router.getCurrentQuery.mockReturnValue(new URLSearchParams())
      document.body.innerHTML = await ragView.render()
      ragView._restoreSearchFromRoute()
      expect(document.getElementById("rag-search-input").value).toBe("")
      expect(ragView._lastExecutedRouteSignature).toBe("")

      router.getCurrentQuery.mockReturnValue(query)
      document.body.innerHTML = await ragView.render()
      ragView._restoreSearchFromRoute()
      await vi.waitFor(() => expect(api.context.searchEvidence).toHaveBeenCalledTimes(2))
      expect(document.getElementById("rag-results").textContent).toContain("旧塔结果")
    })

    it("项目切换后旧证据抽屉响应不能覆盖当前抽屉引用", async () => {
      state.currentProjectId = "p1"
      ragView._searchHits = [{
        title: "旧项目命中",
        source_ref: { content_mode: "canonical", chapter_index: 1, version_number: 1 },
      }]
      document.body.innerHTML = '<aside id="rag-evidence-drawer"></aside>'
      let resolveRead
      api.context.readEvidence.mockImplementation(() => new Promise((resolve) => {
        resolveRead = resolve
      }))
      const pending = ragView._openHit(0)

      state.currentProjectId = "p2"
      ragView._resetSearchState()
      document.body.innerHTML = '<aside id="rag-evidence-drawer">当前项目抽屉</aside>'
      resolveRead({
        title: "旧项目证据",
        text: "不应写回",
        source_ref: { chapter_index: 1, version_number: 1 },
        object_refs: [{ target_id: "old-object" }],
      })
      await pending

      expect(document.getElementById("rag-evidence-drawer").textContent).toBe("当前项目抽屉")
      expect(ragView._drawerRefs).toEqual([])
    })

    it("提交检索把查询与筛选写入 URL，但不保存加载游标", async () => {
      state.currentProjectId = "p1"
      router.getCurrentQuery.mockReturnValue(new URLSearchParams())
      router.navigate.mockResolvedValue(true)
      document.body.innerHTML = `
        <input id="rag-search-input" value="旧塔" />
        <select id="rag-search-kind"><option value="smart" selected>smart</option></select>
        <select id="rag-content-mode"><option value="canonical" selected>canonical</option></select>
        <select id="rag-visibility-mode"><option value="author" selected>author</option></select>
        <input type="checkbox" data-search-scope="manuscript" checked />
        <input type="checkbox" data-search-scope="world" checked />
      `

      await ragView._submitSearchFromForm()

      const route = router.navigate.mock.calls.at(-1)[3]
      expect(router.navigate).toHaveBeenLastCalledWith("rag", "search", true, route)
      expect(route.get("q")).toBe("旧塔")
      expect(route.getAll("scope")).toEqual(["manuscript", "world"])
      expect(route.has("page")).toBe(false)
      expect(route.has("cursor")).toBe(false)
      expect(route.has("cutoff_offset")).toBe(false)
    })
  })

  it("技术诊断按需加载隐私安全的检索记录", async () => {
    state.currentProjectId = "p1"
    api.context.listRetrievalTraces.mockResolvedValue({
      items: [{
        id: "trace-1",
        content_mode: "canonical",
        retrieval_purpose: "scene_context",
        candidate_count: 12,
        unique_count: 8,
        hydrated_count: 5,
        drop_counts: { stale_hash: 2, visibility: 1 },
        safe_empty_reason: "no_visible_evidence",
        warning_codes: ["safe_empty"],
        created_at: "2026-07-12T08:00:00Z",
      }],
    })
    document.body.innerHTML = `<div id="rag-diagnostics">${ragView._renderDiagnostics()}</div>`

    await ragView._loadRetrievalTraces()

    expect(api.context.listRetrievalTraces).toHaveBeenCalledWith("p1", {
      content_mode: "canonical",
      limit: 20,
    })
    expect(document.getElementById("rag-diagnostics").textContent).toContain("scene_context")
    expect(document.getElementById("rag-diagnostics").textContent).toContain("候选 12")
    expect(document.getElementById("rag-diagnostics").textContent).toContain("丢弃 3")
    expect(document.getElementById("rag-diagnostics").textContent).toContain("no_visible_evidence")
  })

  it("重试失败的 RAG 任务后恢复轮询", async () => {
    state.currentProjectId = "p1"
    ragView._rebuildProgress = {
      taskId: "task-1",
      taskType: "rag_reindex_novel",
      workflowType: "rag_reindex_novel",
      availableActions: ["retry"],
      raw: { task_id: "task-1", task_type: "rag_reindex_novel" },
    }
    document.body.innerHTML = '<div id="rag-rebuild-progress"></div>'
    api.tasks.retry.mockResolvedValue({ task_id: "task-1", status: "pending", attempt: 1, max_attempts: 2 })
    const polling = vi.spyOn(ragView, "_startRebuildPolling").mockImplementation(() => {})

    await expect(ragView._retryFailedTask()).resolves.toBe(true)

    expect(api.tasks.retry).toHaveBeenCalledWith("task-1", "p1")
    expect(ragView._rebuildProgress.status).toBe("pending")
    expect(polling).toHaveBeenCalledWith("task-1", "rag_reindex_novel")
    polling.mockRestore()
  })

  it("重试请求失败时保留原失败任务卡", async () => {
    state.currentProjectId = "p1"
    const failedProgress = {
      taskId: "task-1",
      workflowType: "rag_reindex_novel",
      availableActions: ["retry"],
      raw: { task_id: "task-1", task_type: "rag_reindex_novel" },
    }
    ragView._rebuildProgress = failedProgress
    document.body.innerHTML = '<div id="rag-rebuild-progress"></div>'
    api.tasks.retry.mockRejectedValue(new Error("重试配额已耗尽"))

    await expect(ragView._retryFailedTask()).resolves.toBe(false)

    expect(ragView._rebuildProgress).toBe(failedProgress)
    expect(ragView._taskRetryPending).toBe(false)
    expect(toast).toHaveBeenCalledWith("重试配额已耗尽", "error")
  })

  it("检索记录加载失败只在诊断区显示错误", async () => {
    state.currentProjectId = "p1"
    document.body.innerHTML = `<div id="rag-diagnostics">${ragView._renderDiagnostics()}</div>`
    api.context.listRetrievalTraces.mockRejectedValue(new Error("暂时不可用"))

    await ragView._loadRetrievalTraces()

    expect(ragView._retrievalTracesState).toBe("error")
    expect(document.getElementById("rag-diagnostics").textContent).toContain("检索记录加载失败：暂时不可用")
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("暂时不可用"), expect.anything())
  })

  it("智能搜索传递正文版本、可见性和范围", async () => {
    state.currentProjectId = "p1"
    document.body.innerHTML = `
      <div id="rag-results"></div>
      <select id="rag-search-kind"><option value="smart" selected>smart</option></select>
      <select id="rag-content-mode"><option value="working" selected>working</option></select>
      <select id="rag-visibility-mode"><option value="reader" selected>reader</option></select>
      <input id="rag-cutoff-chapter" value="80" />
      <select id="rag-cutoff-scene-id"><option value="scene-80" selected>scene-80</option></select>
      <input id="rag-cutoff-offset" value="320" />
      <input type="checkbox" data-search-scope="manuscript" checked />
      <input type="checkbox" data-search-scope="outline" checked />
    `
    api.context.searchEvidence = vi.fn().mockResolvedValue({ hits: [] })

    await ragView._doSearch("铜铃")

    expect(api.context.searchEvidence).toHaveBeenCalledWith(
      expect.objectContaining({
        novel_id: "p1",
        query: "铜铃",
        content_mode: "working",
        visibility: expect.objectContaining({
          mode: "reader",
          cutoff_chapter: 80,
          cutoff_scene_id: "scene-80",
          cutoff_offset: 320,
        }),
        scopes: ["manuscript", "outline"],
        include_pending_objects: false,
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it("待处理世界对象必须显式勾选才进入智能检索", () => {
    document.body.innerHTML = `
      <input type="checkbox" id="rag-include-pending" checked />
      <input type="checkbox" data-search-scope="world" checked />
    `

    expect(ragView._buildEvidencePayload("星门")).toMatchObject({
      scopes: ["world"],
      include_pending_objects: true,
    })
  })

  it("字面搜索锁定正文范围", () => {
    document.body.innerHTML = `
      <select id="rag-search-kind"><option value="literal" selected>literal</option></select>
      <input type="checkbox" data-search-scope="manuscript" />
      <input type="checkbox" data-search-scope="world" checked />
      <input type="checkbox" data-search-scope="outline" checked />
    `

    ragView._toggleSearchScopes("literal")

    const manuscript = document.querySelector('[data-search-scope="manuscript"]')
    const world = document.querySelector('[data-search-scope="world"]')
    const outline = document.querySelector('[data-search-scope="outline"]')
    expect(manuscript.checked).toBe(true)
    expect(manuscript.disabled).toBe(false)
    expect(world.checked).toBe(false)
    expect(world.disabled).toBe(true)
    expect(outline.checked).toBe(false)
    expect(outline.disabled).toBe(true)
  })

  it("字面搜索按章节请求聚合并显示章内命中数", async () => {
    state.currentProjectId = "p1"
    document.body.innerHTML = `
      <div id="rag-results"></div>
      <select id="rag-search-kind"><option value="literal" selected>literal</option></select>
      <select id="rag-content-mode"><option value="canonical" selected>canonical</option></select>
      <select id="rag-visibility-mode"><option value="author" selected>author</option></select>
      <input type="checkbox" data-search-scope="manuscript" checked />
    `
    api.context.grepEvidence.mockResolvedValue({
      total: 2,
      hits: [{
        kind: "manuscript",
        title: "第一章",
        snippet: "克莱恩醒来",
        chapter_index: 1,
        match_count: 7,
        match_basis: "occurrence",
      }],
    })

    await ragView._doSearch("克莱恩")

    expect(api.context.grepEvidence).toHaveBeenCalledWith(
      expect.objectContaining({
        pattern: "克莱恩",
        limit: 100,
        group_by_chapter: true,
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(document.getElementById("rag-results").textContent).toContain("找到 2 个章节结果")
    expect(document.getElementById("rag-results").textContent).toContain("本章 7 处命中")
  })

  it("切换检索方式时更新简要说明", () => {
    document.body.innerHTML = '<p id="rag-search-kind-help"></p>'

    ragView._updateSearchKindHelp("literal")
    expect(document.getElementById("rag-search-kind-help").textContent).toContain("完全相同的文字")

    ragView._updateSearchKindHelp("smart")
    expect(document.getElementById("rag-search-kind-help").textContent).toContain("语义相关性")
  })

  it("零命中时仍显示工作稿索引警告", async () => {
    state.currentProjectId = "p1"
    document.body.innerHTML = `
      <div id="rag-results"></div>
      <select id="rag-search-kind"><option value="smart" selected>smart</option></select>
      <select id="rag-content-mode"><option value="working" selected>working</option></select>
      <select id="rag-visibility-mode"><option value="author" selected>author</option></select>
      <input type="checkbox" data-search-scope="manuscript" checked />
    `
    api.context.searchEvidence = vi.fn().mockResolvedValue({
      hits: [],
      degraded: true,
      warnings: ["工作稿索引更新中/需重建，过期片段不会返回"],
    })

    await ragView._doSearch("铜铃")

    expect(document.getElementById("rag-results")?.textContent).toContain("工作稿索引更新中")
    expect(document.getElementById("rag-results")?.textContent).toContain("未找到匹配结果")
  })

  it("高亮片段会转义用户动态内容", () => {
    const html = ragView._highlightSnippet('<img src=x onerror="boom">', "img")
    expect(html).toContain("&lt;<mark>img</mark>")
    expect(html).not.toContain("<img")
    expect(html).toContain("&quot;boom&quot;")
  })

  it("索引状态会转义 API 返回的动态计数", async () => {
    state.currentSubView = "status"
    ragView._totalChunks = '<img src=x onerror="boom">'
    ragView._embeddingFailedCount = '<script>alert(1)</script>'

    const html = await ragView.render()

    expect(html).toContain("&lt;img")
    expect(html).toContain("&lt;script&gt;")
    expect(html).not.toContain("<img src=x")
    expect(html).not.toContain("<script>alert")
  })

  it("对象跳转使用已检查的名称作为对象库查询", async () => {
    state.currentProjectId = "p1"
    ragView._drawerRefs = [{
      target_type: "world_entity",
      target_id: "entity-1",
      target_name: "旧塔密钥",
    }]

    await ragView._navigateObjectRef(0)

    expect(router.navigate).toHaveBeenCalledWith(
      "world",
      "objects",
      true,
      expect.any(URLSearchParams),
    )
    const query = router.navigate.mock.calls.at(-1)[3]
    expect(query.get("q")).toBe("旧塔密钥")
  })


  describe("_rebuildIndex", () => {
    it.each([
      {
        name: "无项目时显示警告",
        projectId: null,
        body: "",
        rebuildResponse: {},
        statusResponse: null,
        expectedPayload: null,
        expectedToasts: [["请先选择项目", "warning"]],
      },
      {
        name: "提交重建任务后刷新状态",
        projectId: "p1",
        body: "",
        rebuildResponse: { total: 1, task_id: "task-1", warnings: ["embedding 失败"] },
        statusResponse: { total: 10 },
        expectedPayload: { novel_id: "p1" },
        expectedToasts: [["索引重建任务已提交", "success"], ["embedding 失败", "warning"]],
      },
      {
        name: "按章节范围重建索引时提交起始和结束章节",
        projectId: "p1",
        body: `<input id="rag-rebuild-start" value="2" /><input id="rag-rebuild-end" value="5" />`,
        rebuildResponse: { task_id: "task-2", status: "pending" },
        statusResponse: null,
        expectedPayload: { novel_id: "p1", start_chapter: 2, end_chapter: 5 },
        expectedToasts: [["索引重建任务已提交", "success"]],
      },
    ])("$name", async ({ projectId, body, rebuildResponse, statusResponse, expectedPayload, expectedToasts }) => {
      state.currentProjectId = projectId
      document.body.innerHTML = body
      api.rag.rebuild.mockResolvedValue(rebuildResponse)
      if (statusResponse) {
        api.rag.status.mockResolvedValue(statusResponse)
      }

      await ragView._rebuildIndex()

      if (expectedPayload) {
        expect(api.rag.rebuild).toHaveBeenCalledWith(expectedPayload, expect.objectContaining({ signal: expect.any(AbortSignal) }))
      }
      for (const toastMessage of expectedToasts) {
        expect(toast).toHaveBeenCalledWith(toastMessage[0], toastMessage[1])
      }
    })

    it("提交任务后用真实任务进度卡展示完成摘要", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = '<div id="rag-rebuild-progress"></div>'
      api.rag.rebuild.mockResolvedValue({ task_id: "task-rag", status: "pending" })
      api.tasks.get.mockResolvedValue({
        task_id: "task-rag",
        task_type: "rag_reindex_novel",
        status: "done",
        progress: 1,
        result: {
          total_chapters: 3,
          chunks_created: 18,
          embedding_failed_count: 1,
          warnings: ["第 2 章 embedding 降级"],
        },
      })

      await ragView._rebuildIndex()
      await vi.waitFor(() => {
        const html = document.getElementById("rag-rebuild-progress")?.innerHTML || ""
        expect(html).toContain("3 章，18 个片段，1 个嵌入失败")
        expect(html).toContain("第 2 章 embedding 降级")
      })

      expect(api.tasks.get).toHaveBeenCalledWith("task-rag")
    })

    it("无任务 ID 且无可处理内容时显示普通空状态", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = '<div id="rag-rebuild-progress"></div>'
      api.rag.rebuild.mockResolvedValue({ status: "done", total: 0 })

      await ragView._rebuildIndex()

      expect(api.tasks.get).not.toHaveBeenCalled()
      expect(document.getElementById("rag-rebuild-progress")?.innerHTML).toContain("暂无可索引工作稿")
    })

    it("onEnter 恢复未完成的 RAG 重建任务", async () => {
      state.currentProjectId = "p1"
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: "p1:rag_reindex_novel:task-rag-restore",
        taskId: "task-rag-restore",
        workflowType: "rag_reindex_novel",
        projectId: "p1",
        view: "rag",
      }]))
      api.rag.status.mockResolvedValue({ total: 0, items: [] })
      api.tasks.get.mockResolvedValue({
        task_id: "task-rag-restore",
        task_type: "rag_reindex_novel",
        status: "running",
        progress: 0.25,
      })

      await ragView.onEnter()

      expect(api.tasks.get).toHaveBeenCalledWith("task-rag-restore")
      expect(ragView._rebuildProgress.percent).toBe(25)
    })

    it("onEnter 后台预热 worker 且不阻塞状态渲染", async () => {
      state.currentProjectId = "p1"
      api.rag.status.mockResolvedValue({
        total: 3,
        items: [],
        embedding_runtime: { started: false, healthy: false, cache_stats: {} },
      })
      api.rag.prewarm.mockResolvedValue({
        status: "ready",
        embedding_dim: 768,
        latency_ms: 12,
        cache_stats: { hits: 0, misses: 1 },
      })

      await ragView.onEnter()
      expect(ragView._totalChunks).toBe(3)
      expect(api.rag.prewarm).toHaveBeenCalled()
      await vi.waitFor(() => {
        expect(ragView._prewarmState).toBe("ready")
      })
    })

    it("预热失败时显示 warning 且保留索引列表", async () => {
      document.body.innerHTML = '<div id="rag-diagnostics"></div>'
      ragView._statusItems = [{ text: "保留片段", source_type: "chapter_text" }]
      api.rag.prewarm.mockRejectedValue(new Error("worker down"))

      await ragView._prewarm()

      expect(ragView._prewarmState).toBe("failed")
      expect(ragView._prewarmWarning).toContain("worker down")
      expect(ragView._statusItems[0].text).toBe("保留片段")
    })

    it("重试失败向量提交任务并复用任务轮询", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = '<div id="rag-rebuild-progress"></div>'
      ragView._retryableEmbeddingCount = 2
      api.rag.retryEmbeddings.mockResolvedValue({ task_id: "task-retry", status: "pending" })
      api.rag.status.mockResolvedValue({ total: 10, embedding_failed_count: 0, retryable_embedding_count: 0, items: [] })
      api.tasks.get.mockResolvedValue({
        task_id: "task-retry",
        task_type: "rag_retry_embeddings",
        status: "done",
        progress: 1,
        result: { total: 2, succeeded: 2, failed: 0, warnings: [] },
      })

      await ragView._retryEmbeddings()

      expect(api.rag.retryEmbeddings).toHaveBeenCalledWith({
        novel_id: "p1",
        statuses: ["failed", "pending_vectorization"],
      }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
      expect(api.tasks.get).toHaveBeenCalledWith("task-retry")
      await vi.waitFor(() => {
        expect(api.rag.status).toHaveBeenCalledWith("p1")
      })
    })

    it("onEnter 恢复未完成的 RAG 向量重试任务", async () => {
      state.currentProjectId = "p1"
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: "p1:rag_retry_embeddings:task-rag-retry-restore",
        taskId: "task-rag-retry-restore",
        workflowType: "rag_retry_embeddings",
        projectId: "p1",
        view: "rag",
      }]))
      api.rag.status.mockResolvedValue({ total: 3, items: [] })
      api.tasks.get.mockResolvedValue({
        task_id: "task-rag-retry-restore",
        task_type: "rag_retry_embeddings",
        status: "running",
        progress: 0.5,
      })

      await ragView.onEnter()

      expect(api.tasks.get).toHaveBeenCalledWith("task-rag-retry-restore")
      expect(ragView._rebuildProgress.workflowType).toBe("rag_retry_embeddings")
      expect(ragView._rebuildProgress.percent).toBe(50)
    })

    it("无可重试向量时不提交重试任务", async () => {
      state.currentProjectId = "p1"
      ragView._retryableEmbeddingCount = 0

      await ragView._retryEmbeddings()

      expect(api.rag.retryEmbeddings).not.toHaveBeenCalled()
      expect(toast).toHaveBeenCalledWith("暂无可重试的失败向量", "info")
    })

    it("_prewarm background 不触发 DOM 更新", async () => {
      const updateSpy = vi.spyOn(ragView, "_updateDiagnosticsDOM").mockImplementation(() => {})
      api.rag.prewarm.mockResolvedValue({ status: "ready" })

      await ragView._prewarm({ background: true })

      expect(updateSpy).not.toHaveBeenCalled()
      expect(ragView._prewarmState).toBe("ready")
      updateSpy.mockRestore()
    })

    it("_prewarm 非后台模式更新 DOM", async () => {
      const updateSpy = vi.spyOn(ragView, "_updateDiagnosticsDOM").mockImplementation(() => {})
      api.rag.prewarm.mockResolvedValue({ status: "ready" })

      await ragView._prewarm()

      expect(updateSpy).toHaveBeenCalledTimes(2)
      updateSpy.mockRestore()
    })

    it("chunks_created 为 0 时不回退到旧 total", () => {
      ragView._totalChunks = 10
      ragView._applyRagRebuildResult({ total_chapters: 3, chunks_created: 0 })
      expect(ragView._totalChunks).toBe(0)
    })

    it("重建结果缺 chunks_created 时刷新服务端状态，避免保留旧片段数", async () => {
      state.currentProjectId = "p1"
      ragView._totalChunks = 10
      api.rag.status.mockResolvedValue({
        total: 7,
        embedding_failed_count: 1,
        retryable_embedding_count: 1,
        items: [],
      })

      await ragView._applyRagRebuildResult({ total_chapters: 3 })

      expect(api.rag.status).toHaveBeenCalledWith("p1")
      expect(ragView._totalChunks).toBe(7)
      expect(ragView._embeddingFailedCount).toBe(1)
    })

    it("证据结果中 hits 非数组时兜底为空数组", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = '<div id="rag-results"></div>'
      api.context.searchEvidence.mockResolvedValue({ hits: null })

      await ragView._doSearch("test")

      expect(document.getElementById("rag-results").textContent).toContain("未找到匹配结果")
    })

    it("证据 hits 数组会按统一结果渲染", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = '<div id="rag-results"></div>'
      api.context.searchEvidence.mockResolvedValue({
        hits: [{ snippet: "统一证据", kind: "manuscript" }],
      })

      await ragView._doSearch("test")

      expect(document.getElementById("rag-results").textContent).toContain("统一证据")
    })

    it("统一证据接口缺失时不回退展示旧 RAG chunk", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = '<div id="rag-results"></div>'
      delete api.context.searchEvidence
      api.rag.search.mockResolvedValue({
        chunks: [{ text: "过期旧片段", source_type: "chapter_text" }],
      })

      await ragView._doSearch("test")

      const text = document.getElementById("rag-results").textContent
      expect(text).toContain("证据检索接口不可用")
      expect(text).not.toContain("过期旧片段")
      expect(api.rag.search).not.toHaveBeenCalled()
    })

    it("重建索引成功后清空 API 缓存", async () => {
      state.currentProjectId = "p1"
      api.rag.rebuild.mockResolvedValue({ task_id: "task-1" })

      await ragView._rebuildIndex()

      expect(api.clearCache).toHaveBeenCalled()
    })

    it("重试向量成功后清空 API 缓存", async () => {
      state.currentProjectId = "p1"
      ragView._retryableEmbeddingCount = 2
      api.rag.retryEmbeddings.mockResolvedValue({ task_id: "task-retry" })

      await ragView._retryEmbeddings()

      expect(api.clearCache).toHaveBeenCalled()
    })

    it("onLeave 中止进行中的长请求", () => {
      const controller = new AbortController()
      ragView._abortController = controller
      const abortSpy = vi.spyOn(controller, "abort")

      ragView.onLeave()

      expect(abortSpy).toHaveBeenCalled()
      expect(ragView._abortController).toBeNull()
    })

    it("长请求调用携带 abort signal", async () => {
      state.currentProjectId = "p1"
      ragView._abortController = new AbortController()
      ragView._retryableEmbeddingCount = 2
      api.context.searchEvidence.mockResolvedValue({ hits: [] })
      api.rag.rebuild.mockResolvedValue({ task_id: "task-1" })
      api.rag.retryEmbeddings.mockResolvedValue({ task_id: "task-retry" })
      api.rag.prewarm.mockResolvedValue({ status: "ready" })

      document.body.innerHTML = '<div id="rag-results"></div>'
      await ragView._doSearch("q")
      await ragView._rebuildIndex()
      await ragView._retryEmbeddings()
      await ragView._prewarm({ signal: ragView._abortController.signal })
      ragView.onLeave()

      expect(api.context.searchEvidence.mock.calls[0][1]).toMatchObject({ signal: expect.any(AbortSignal) })
      expect(api.rag.rebuild.mock.calls[0][1]).toMatchObject({ signal: expect.any(AbortSignal) })
      expect(api.rag.retryEmbeddings.mock.calls[0][1]).toMatchObject({ signal: expect.any(AbortSignal) })
      expect(api.rag.prewarm.mock.calls[0][0]).toMatchObject({ signal: expect.any(AbortSignal) })
    })
  })
})
