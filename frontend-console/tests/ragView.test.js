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
  ragView._searchHits = []
  ragView._lastSearchPayload = null
  api.context.searchEvidence = vi.fn()
  api.context.grepEvidence = vi.fn()
  api.context.readEvidence = vi.fn()
  api.context.inspectEvidence = vi.fn()
  api.context.traceEvidence = vi.fn()
  vi.clearAllMocks()
})

describe("ragView", () => {
  describe("ragView render", () => {
    it.each([
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
        expected: ["检索方式", "字面搜索", "可见视角"],
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
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
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
      expect(document.getElementById("rag-rebuild-progress")?.innerHTML).toContain("暂无可索引草稿")
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
