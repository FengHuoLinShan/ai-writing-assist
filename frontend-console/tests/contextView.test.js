import { describe, it, expect, vi, beforeEach } from "vitest"
import contextView from "../views/contextView.js"

beforeEach(() => { vi.clearAllMocks(); contextView._lastBundle = null })

describe("contextView", () => {
  describe("contextView render", () => {
    it("包含编译和渲染按钮", async () => {
      const html = await contextView.render()
      expect(html).toContain("data-action")
      expect(html).toContain("compile")
      expect(html).toContain("render-md")
    })
  })

  describe("compile", () => {
    it("无项目时警告", async () => {
      state.currentProjectId = null
      document.body.innerHTML = '<div id="ctx-output"></div><div id="ctx-task"></div>'
      await contextView.compile()
      expect(globalThis.toast).toHaveBeenCalledWith("请先选择项目", "warning")
    })

    it("无任务描述时警告", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = '<div id="ctx-output"></div><div id="ctx-task"></div>'
      await contextView.compile()
      expect(globalThis.toast).toHaveBeenCalledWith("请输入任务描述", "warning")
    })

    it("调用 API 并渲染结果", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = `
        <div id="ctx-output"></div>
        <textarea id="ctx-task">生成章节卡</textarea>
        <select id="ctx-scope"><option value="arc">篇章</option></select>
        <select id="ctx-reveal"><option value="author_safe">安全</option></select>
        <input id="ctx-entities" />
        <input id="ctx-characters" />
        <input id="ctx-chapter" />
        <input id="ctx-scene" />
        <input id="ctx-budget" value="4000" />
      `
      api.context.compile.mockResolvedValue({
        total_tokens: 1200, budget_tokens: 4000, scope: "arc", reveal_mode: "author_safe",
        sections: [
          { key: "project", tier: "core", token_count: 200, truncated: false },
          { key: "characters", tier: "standard", token_count: 1000, truncated: true },
        ],
        evicted: ["rag_chunks"],
        truncated: ["characters"],
        warnings: [],
      })

      await contextView.compile()

      expect(api.context.compile).toHaveBeenCalled()
      const output = document.getElementById("ctx-output")
      expect(output?.innerHTML).toContain("1200")
      expect(output?.innerHTML).toContain("4000")
      expect(output?.innerHTML).toContain("characters")
      expect(output?.innerHTML).toContain("已驱逐")
      expect(output?.innerHTML).toContain("已截断")
    })
  })

})

