import { describe, it, expect, vi, beforeEach } from "vitest"
import generateView from "../views/generateView.js"

beforeEach(() => { vi.clearAllMocks(); generateView._currentType = null })

describe("generateView", () => {
  describe("render", () => {
    it("包含生成类型卡片", async () => {
      const html = await generateView.render()
      expect(html).toContain("世界与人物结构")
      expect(html).toContain("剧情结构")
    })
  })

  describe("_selectType", () => {
    it("设置当前类型并显示输入区", () => {
      document.body.innerHTML = '<div id="generate-input-area" style="display:none;"></div>'

      generateView._selectType("plot")

      expect(generateView._currentType).toBe("plot")
      const area = document.getElementById("generate-input-area")
      expect(area?.style.display).toBe("")
    })
  })

  describe("_startGenerate", () => {
    it("无意图时警告", async () => {
      document.body.innerHTML = '<div id="generate-intent"></div><div id="generate-result"></div>'
      await generateView._startGenerate()
      expect(globalThis.toast).toHaveBeenCalledWith("请输入创作意图描述", "warning")
    })

    it("无类型时警告", async () => {
      document.body.innerHTML = `
        <textarea id="generate-intent">生成内容</textarea>
        <div id="generate-result"></div>
      `
      await generateView._startGenerate()
      expect(globalThis.toast).toHaveBeenCalledWith("请先选择生成类型", "warning")
    })

    it("调用 API 并显示进度", async () => {
      _state.currentProjectId = "p1"
      generateView._currentType = "chapter"
      document.body.innerHTML = `
        <textarea id="generate-intent">生成章节卡</textarea>
        <div id="generate-result"></div>
        <select id="generate-scope"><option value="arc">篇章</option></select>
        <input id="generate-related" />
      `
      api.context.compile.mockResolvedValue({})
      api.generate.chapterScene.mockResolvedValue({ id: "task-1", status: "running" })

      await generateView._startGenerate()

      expect(api.generate.chapterScene).toHaveBeenCalled()
      const result = document.getElementById("generate-result")
      expect(result?.innerHTML).toContain("任务已提交")
    })
  })
})
