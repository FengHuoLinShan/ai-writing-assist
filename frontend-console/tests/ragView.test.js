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
        expected: ["诊断", "实际维度", "768", "配置维度", "1024", "ready", "123.4ms", "重试失败向量"],
      },
      {
        name: "status 子视图包含索引状态",
        subView: "status",
        setup: () => {},
        expected: ["索引状态"],
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
        expected: ["搜索关键词"],
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
        response: { chunks: [{ text: "测试结果", source_type: "chapter_text", score: 0.85 }] },
        expectedCall: { query: "测试", top_k: 8, mode: "search" },
        expectedInHtml: ["测试结果"],
      },
      {
        name: "搜索降级时显示准确性提示",
        projectId: "p1",
        query: "测试",
        body: '<div id="rag-results"></div>',
        response: { degraded: true, warnings: ["embedding 生成失败，本次结果可能不准确"], chunks: [{ text: "测试结果", source_type: "chapter_text", score: 0.5 }] },
        expectedInHtml: ["本次结果可能不准确", "测试结果"],
      },
      {
        name: "搜索结果为空时显示提示",
        projectId: null,
        query: "不存在",
        body: '<div id="rag-results"></div>',
        response: { chunks: [] },
        expectedInHtml: ["未找到匹配结果"],
      },
      {
        name: "无结果容器时不操作",
        projectId: null,
        query: "test",
        body: "",
        response: { chunks: [] },
        expectUndefined: true,
      },
    ])("$name", async ({ projectId, query, body, response, expectedCall, expectedInHtml, expectUndefined }) => {
      document.body.innerHTML = body
      if (projectId) state.currentProjectId = projectId
      api.rag.search.mockResolvedValue(response)

      const result = ragView._doSearch(query)
      if (expectUndefined) {
        await expect(result).resolves.toBeUndefined()
        return
      }
      await result
      if (expectedCall) {
        expect(api.rag.search).toHaveBeenCalledWith(expectedCall, projectId)
      }
      const results = document.getElementById("rag-results")
      for (const text of expectedInHtml) {
        expect(results?.innerHTML).toContain(text)
      }
    })
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
        expect(api.rag.rebuild).toHaveBeenCalledWith(expectedPayload)
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
      })
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
  })
})
