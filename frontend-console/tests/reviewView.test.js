/**
 * reviewView 测试
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import reviewView from "../views/reviewView.js"

beforeEach(() => {
  vi.clearAllMocks()
})

describe("reviewView", () => {
  describe("render", () => {
    it("返回包含复查按钮的 HTML", async () => {
      const html = await reviewView.render()
      expect(html).toContain("结构复查")
      expect(html).toContain("运行复查")
      expect(html).toContain("data-action")
    })
  })

  describe("runReview", () => {
    it("调用 API 并渲染结果到 output", async () => {
      // 设置 DOM
      document.body.innerHTML = '<div id="review-output"></div>'

      api.review.run.mockResolvedValue({
        decision: "pass",
        score: 0.95,
        problems: [],
        revision_instructions: ["增加第2章冲突烈度"],
      })

      await reviewView.runReview()

      expect(api.review.run).toHaveBeenCalledWith({
        novel_id: null,
        target_type: "chapter_cards",
        candidate_payload: {},
      })
      const output = document.getElementById("review-output")
      expect(output?.innerHTML).toContain("pass")
      expect(output?.innerHTML).toContain("增加第2章冲突烈度")
    })

    it("API 失败时显示错误", async () => {
      document.body.innerHTML = '<div id="review-output"></div>'

      api.review.run.mockRejectedValue(new Error("LLM 不可用"))

      await reviewView.runReview()

      const output = document.getElementById("review-output")
      expect(output?.innerHTML).toContain("LLM 不可用")
    })

    it("output 元素不存在时不报错", async () => {
      document.body.innerHTML = "" // 没有 review-output

      await expect(reviewView.runReview()).resolves.toBeUndefined()
    })

    it("显示合并后的所有问题类型", async () => {
      document.body.innerHTML = '<div id="review-output"></div>'

      api.review.run.mockResolvedValue({
        decision: "minor_revision",
        problems: [{ message: "Schema 问题", severity: "high" }],
        conflict_warnings: [{ message: "时间线冲突", severity: "medium" }],
        early_reveal_warnings: [{ message: "提前揭示", severity: "low" }],
        character_knowledge_warnings: [{ message: "知识越界", severity: "medium" }],
        duplicate_entity_warnings: [{ message: "重复实体", severity: "low" }],
      })

      await reviewView.runReview()

      const output = document.getElementById("review-output")
      expect(output?.innerHTML).toContain("Schema 问题")
      expect(output?.innerHTML).toContain("时间线冲突")
      expect(output?.innerHTML).toContain("提前揭示")
      expect(output?.innerHTML).toContain("知识越界")
      expect(output?.innerHTML).toContain("重复实体")
    })
  })
})
