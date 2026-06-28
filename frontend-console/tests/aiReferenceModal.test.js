import { describe, it, expect, vi, beforeEach } from "vitest"
import { confirmAiReference } from "../shared/aiReferenceModal.js"
import { clearDocument } from "./helpers.js"

function mountModalDom() {
  document.body.innerHTML = `
    <div id="modal-overlay" class="hidden">
      <div id="modal-title"></div>
      <div id="modal-body"></div>
      <div id="modal-footer"></div>
    </div>
  `
}

beforeEach(() => {
  clearDocument()
  mountModalDom()
  vi.clearAllMocks()
})

describe("aiReferenceModal", () => {
  it("渲染默认选择且不提供 Markdown textarea", () => {
    confirmAiReference({
      novel_id: "p1",
      action: "outline.generate",
      task: "剧情结构生成",
      scope: "chapter",
      chapter_index: 3,
      include_pending_objects: true,
    }).catch(() => {})

    expect(document.getElementById("modal-title")?.textContent).toBe("AI 参考资料")
    expect(document.getElementById("ai-ref-scope")?.value).toBe("chapter")
    expect(document.getElementById("ai-ref-chapter")?.value).toBe("3")
    expect(document.body.textContent).toContain("待确认对象")
    expect(document.body.textContent).not.toContain("candidate asset")
    expect(document.body.textContent).not.toContain("Markdown")
    expect(document.querySelector("#ai-ref-markdown")).toBeNull()
  })

  it("重新整理会提交当前选择并渲染摘要", async () => {
    api.context.confirm.mockResolvedValue({
      id: "c1",
      context_mode: "working",
      include_pending_objects: true,
      scope: "chapter",
      selected_asset_ids: { project: ["p1"], context_sections: ["project", "world"] },
      warnings: ["范围较大"],
      compiled_at: "2026-06-28T00:00:00Z",
    })
    confirmAiReference({
      novel_id: "p1",
      action: "world.entities.extract",
      task: "世界对象补抽",
      scope: "chapter",
      chapter_index: 1,
      include_pending_objects: true,
    }).catch(() => {})

    document.getElementById("ai-ref-context-mode").value = "working"
    document.getElementById("ai-ref-user-note").value = "只补抽长期资产"
    document.querySelector("#modal-footer button")?.click()
    await Promise.resolve()
    await Promise.resolve()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(api.context.confirm).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      action: "world.entities.extract",
      context_mode: "working",
      include_pending_objects: true,
      user_note: "只补抽长期资产",
    }))
    expect(document.getElementById("ai-ref-summary")?.innerHTML).toContain("context_sections: 2")
    expect(document.getElementById("ai-ref-summary")?.textContent).toContain("范围较大")
  })

  it("确认使用返回 context_confirmation_id 来源记录", async () => {
    api.context.confirm.mockResolvedValue({
      id: "confirm-1",
      context_mode: "canonical",
      include_pending_objects: false,
      scope: "full",
      selected_asset_ids: {},
      warnings: [],
    })
    const promise = confirmAiReference({
      novel_id: "p1",
      action: "writing.generate",
      task: "生成正文候选草稿",
      scope: "full",
    })

    const buttons = document.querySelectorAll("#modal-footer button")
    buttons[1].click()
    const result = await promise

    expect(result.id).toBe("confirm-1")
    expect(document.getElementById("modal-overlay")?.classList.contains("hidden")).toBe(true)
  })
})
