import { describe, it, expect, vi, beforeEach } from "vitest"
import ragView from "../views/ragView.js"

beforeEach(() => { vi.clearAllMocks() })

describe("ragView", () => {
  describe("render", () => {
    it("status 子视图包含索引状态", async () => {
      _state.currentSubView = "status"
      const html = await ragView.render()
      expect(html).toContain("索引状态")
    })

    it("search 子视图包含搜索框", async () => {
      _state.currentSubView = "search"
      const html = await ragView.render()
      expect(html).toContain("搜索关键词")
    })
  })

  describe("_doSearch", () => {
    it("渲染搜索结果到 DOM", async () => {
      document.body.innerHTML = '<div id="rag-results"></div>'
      _state.currentProjectId = "p1"
      api.rag.search.mockResolvedValue({
        chunks: [{ text: "测试结果", source_type: "chapter_text", score: 0.85 }],
      })

      await ragView._doSearch("测试")

      expect(api.rag.search).toHaveBeenCalledWith({ query: "测试", top_k: 8 }, "p1")
      const results = document.getElementById("rag-results")
      expect(results?.innerHTML).toContain("测试结果")
    })

    it("搜索结果为空时显示提示", async () => {
      document.body.innerHTML = '<div id="rag-results"></div>'
      api.rag.search.mockResolvedValue({ chunks: [] })

      await ragView._doSearch("不存在")

      const results = document.getElementById("rag-results")
      expect(results?.innerHTML).toContain("未找到匹配结果")
    })

    it("无结果容器时不操作", async () => {
      document.body.innerHTML = ""
      await expect(ragView._doSearch("test")).resolves.toBeUndefined()
    })
  })

  describe("_rebuildIndex", () => {
    it("无项目时显示警告", async () => {
      _state.currentProjectId = null

      await ragView._rebuildIndex()

      expect(toast).toHaveBeenCalledWith("请先选择项目", "warning")
    })

    it("提交重建任务后刷新状态", async () => {
      _state.currentProjectId = "p1"
      api.rag.rebuild.mockResolvedValue({ total: 2 })
      api.rag.status.mockResolvedValue({ total: 10 })

      await ragView._rebuildIndex()

      expect(api.rag.rebuild).toHaveBeenCalledWith({ novel_id: "p1" })
      expect(toast).toHaveBeenCalledWith("索引重建任务已提交：2 章", "success")
    })
  })
})
