import { describe, it, expect, vi, beforeEach } from "vitest"
import generateView from "../views/generateView.js"

beforeEach(() => {
  vi.useRealTimers()
  vi.clearAllMocks()
  localStorage.clear()
  if (generateView._activePoller?.stop) generateView._activePoller.stop()
  generateView._currentType = null
  generateView._activePoller = null
})

describe("generateView", () => {
  describe("generateView render", () => {
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

    it("章节与场景结构生成复用结构生成任务并显示进度", async () => {
      state.currentProjectId = "p1"
      generateView._currentType = "chapter"
      document.body.innerHTML = `
        <textarea id="generate-intent">生成章节卡</textarea>
        <div id="generate-result"></div>
        <select id="generate-scope">
          <option value="arc">篇章</option>
          <option value="chapter">章节</option>
          <option value="full" selected>全部</option>
        </select>
        <input id="generate-related" />
        <div id="modal-overlay" class="hidden">
          <div id="modal-title"></div>
          <div id="modal-body"></div>
          <div id="modal-footer"></div>
        </div>
      `
      api.context.confirm.mockResolvedValue({ id: "confirm-1", selected_asset_ids: {}, warnings: [] })
      api.generate.plotStructure.mockResolvedValue({ id: "task-1", status: "running" })
      api.tasks.get.mockResolvedValue({ task_id: "task-1", task_type: "outline_generate", status: "running" })
      document.getElementById("generate-scope").value = "full"

      const promise = generateView._startGenerate()
      await Promise.resolve()
      document.querySelectorAll("#modal-footer button")[1].click()
      await promise

      expect(api.context.confirm).toHaveBeenCalledWith(expect.objectContaining({
        scope: "full",
        context_mode: "working",
        include_pending_objects: true,
      }))
      expect(api.generate.plotStructure).toHaveBeenCalledWith(expect.objectContaining({
        context_confirmation_id: "confirm-1",
      }))
      expect(api.generate.chapterScene).not.toHaveBeenCalled()
      expect(api.tasks.submit).not.toHaveBeenCalled()
      const result = document.getElementById("generate-result")
      expect(result?.innerHTML).toContain("生成章节与场景结构")
      expect(result?.innerHTML).toContain("任务 task-1")
    })

    it("默认篇章范围在 AI 参考确认中映射为全项目资料", () => {
      generateView._currentType = "chapter"

      const config = generateView._actionConfig("生成章节卡", "arc")

      expect(config.scope).toBe("full")
    })

    it("任务失败时显示后端 error_message 而不是运行中", async () => {
      state.currentProjectId = "p1"
      generateView._currentType = "plot"
      document.body.innerHTML = `
        <textarea id="generate-intent">生成剧情</textarea>
        <div id="generate-result"></div>
        <select id="generate-scope"><option value="arc">篇章</option></select>
        <input id="generate-related" />
        <div id="modal-overlay" class="hidden">
          <div id="modal-title"></div>
          <div id="modal-body"></div>
          <div id="modal-footer"></div>
        </div>
      `
      api.context.confirm.mockResolvedValue({ id: "confirm-plot", selected_asset_ids: {}, warnings: [] })
      api.generate.plotStructure.mockResolvedValue({ task_id: "task-fail", status: "running" })
      api.tasks.get.mockResolvedValue({
        task_id: "task-fail",
        task_type: "plot_structure_generate",
        status: "failed",
        error_message: "LLM 配额不足",
      })

      const promise = generateView._startGenerate()
      await Promise.resolve()
      document.querySelectorAll("#modal-footer button")[1].click()
      await promise
      await vi.waitFor(() => {
        expect(document.getElementById("generate-result")?.innerHTML).toContain("LLM 配额不足")
      })

      expect(document.getElementById("generate-result")?.innerHTML).not.toContain("后台运行")
    })

    it("render 后恢复生成中心未完成任务", async () => {
      state.currentProjectId = "p1"
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: "p1:plot_structure_generate:task-restore",
        taskId: "task-restore",
        workflowType: "plot_structure_generate",
        projectId: "p1",
        view: "generate",
        meta: { type: "plot" },
      }]))
      api.tasks.get.mockResolvedValue({
        task_id: "task-restore",
        task_type: "plot_structure_generate",
        status: "running",
      })

      document.body.innerHTML = await generateView.render()
      await vi.waitFor(() => {
        expect(api.tasks.get).toHaveBeenCalledWith("task-restore")
      })

      expect(document.getElementById("generate-result")?.innerHTML).toContain("生成剧情结构")
    })

    it("任务完成后结果区提供模块直达入口", () => {
      document.body.innerHTML = '<div id="generate-result"></div>'

      generateView._renderTaskProgress({
        taskId: "task-done",
        statusLabel: "已完成",
        done: true,
        resultSummary: "剧情线 1，篇章纲 1，Scene 6",
      }, "world_character")

      const html = document.getElementById("generate-result")?.innerHTML || ""
      expect(html).toContain("查看候选")
      expect(html).toContain('data-action="open-generated-destination"')
    })

    it("章节与场景结构完成后提供场景和篇章纲入口", () => {
      document.body.innerHTML = '<div id="generate-result"></div>'

      generateView._renderTaskProgress({
        taskId: "task-done",
        statusLabel: "已完成",
        done: true,
        resultSummary: "剧情线 1，篇章纲 1，Scene 6",
      }, "chapter")

      const html = document.getElementById("generate-result")?.innerHTML || ""
      expect(html).toContain("剧情线 1，篇章纲 1，Scene 6")
      expect(html).toContain("查看场景")
      expect(html).toContain('data-target-view="scene"')
      expect(html).toContain("查看篇章纲")
      expect(html).toContain('data-target-subview="arcs"')
    })
  })
})
