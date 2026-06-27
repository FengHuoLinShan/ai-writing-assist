import { describe, it, expect, vi, beforeEach } from "vitest"
import ragView from "../views/ragView.js"
import { resetState, clearDocument } from "./helpers.js"

beforeEach(() => {
  resetState()
  clearDocument()
  ragView._apiAvailable = true
  ragView._loading = false
  ragView._totalChunks = 0
  ragView._embeddingFailedCount = 0
  ragView._statusDegraded = false
  ragView._statusWarnings = []
  ragView._statusItems = []
  vi.clearAllMocks()
})

describe("ragView", () => {
  describe("ragView render", () => {
    it.each([
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
  })
})
