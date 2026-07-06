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
      expect(html).toContain("ctx-section-required")
      expect(html).toContain("data-action=\"apply-template\"")
      expect(html).toContain("生成剧情线")
    })
  })

  describe("templates", () => {
    it("applies common task templates to task and scope fields", async () => {
      document.body.innerHTML = await contextView.render()

      contextView._applyTemplate("conflict_check")

      expect(document.getElementById("ctx-task")?.value).toContain("检查")
      expect(document.getElementById("ctx-scope")?.value).toBe("chapter")
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
      expect(api.context.compile.mock.calls[0][1]).toMatchObject({ signal: expect.any(AbortSignal) })
      const output = document.getElementById("ctx-output")
      expect(output?.innerHTML).toContain("1200")
      expect(output?.innerHTML).toContain("4000")
      expect(output?.innerHTML).toContain("characters")
      expect(output?.innerHTML).toContain("已驱逐")
      expect(output?.innerHTML).toContain("已截断")
    })

    it("编译成功后保存请求参数供 renderMarkdown 使用", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = `
        <div id="ctx-output"></div>
        <textarea id="ctx-task">任务A</textarea>
        <select id="ctx-scope"><option value="arc" selected>篇章</option></select>
        <select id="ctx-reveal"><option value="author_safe" selected>安全</option></select>
        <input id="ctx-entities" value="e1" />
        <input id="ctx-characters" />
        <input id="ctx-chapter" value="3" />
        <input id="ctx-scene" />
        <input id="ctx-budget" value="4000" />
      `
      api.context.compile.mockResolvedValue({ total_tokens: 100, sections: [] })

      await contextView.compile()

      expect(contextView._lastRequestParams).toMatchObject({
        novel_id: "p1",
        task: "任务A",
        scope: "arc",
        chapter_index: 3,
        budget_tokens: 4000,
        entity_ids: ["e1"],
        reveal_mode: "author_safe",
      })
    })
  })

  describe("renderMarkdown", () => {
    it("使用上次编译保存的参数，而不是当前表单输入", async () => {
      state.currentProjectId = "p1"
      contextView._lastBundle = { sections: [] }
      contextView._lastRequestParams = {
        task: "旧任务",
        scope: "chapter",
        chapter_index: 2,
        scene_id: undefined,
        budget_tokens: 3000,
        entity_ids: undefined,
        character_ids: undefined,
        reveal_mode: "author_full",
        viewpoint_character_id: undefined,
      }
      api.context.render.mockResolvedValue({ markdown: "# 旧任务结果" })

      document.body.innerHTML = `
        <div id="ctx-output"></div>
        <textarea id="ctx-task">新任务</textarea>
        <select id="ctx-scope"><option value="arc" selected>篇章</option></select>
        <select id="ctx-reveal"><option value="author_safe" selected>安全</option></select>
        <input id="ctx-chapter" value="9" />
        <input id="ctx-budget" value="8000" />
      `

      await contextView.renderMarkdown()

      expect(api.context.render).toHaveBeenCalledWith(
        expect.objectContaining({
          task: "旧任务",
          scope: "chapter",
          chapter_index: 2,
          budget_tokens: 3000,
          reveal_mode: "author_full",
        }),
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      )
    })
  })

  describe("abort on leave", () => {
    it("onLeave 中止进行中的请求", () => {
      const controller = new AbortController()
      contextView._abortController = controller
      const abortSpy = vi.spyOn(controller, "abort")

      contextView.onLeave()

      expect(abortSpy).toHaveBeenCalled()
      expect(contextView._abortController).toBeNull()
      expect(contextView._lastBundle).toBeNull()
    })
  })

})
