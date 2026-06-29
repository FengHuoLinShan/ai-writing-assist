import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("../shared/aiReferenceModal.js", () => ({
  confirmAiReference: vi.fn(),
}))

import { confirmAiReference } from "../shared/aiReferenceModal.js"
import { showWritingConflictModal } from "../views/writingConflictModal.js"
import { clearDocument, resetState } from "./helpers.js"

beforeEach(() => {
  resetState({ currentProjectId: "p1" })
  clearDocument()
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: undefined,
  })
  vi.clearAllMocks()
})

describe("writingConflictModal", () => {
  it("escapes evidence text and patches item status", async () => {
    api.writing.updateConflictItem.mockResolvedValue({ id: "i1", status: "later" })
    showWritingConflictModal({
      check: {
        id: "c1",
        items: [
          {
            id: "i1",
            kind: "forbidden_present",
            severity: "high",
            source_module: "outline",
            evidence_summary: "<img src=x onerror=alert(1)>",
            status: "open",
            needs_review: false,
          },
        ],
      },
      novelId: "p1",
      onStatusChanged: vi.fn(),
    })

    const body = showModal.mock.calls[0][1]
    expect(body).toContain("&lt;img")
    expect(body).not.toContain("<img src=x")

    document.body.innerHTML = `<div>${body}</div>`
    document.querySelector('[data-conflict-status="later"]').click()
    await Promise.resolve()

    expect(api.writing.updateConflictItem).toHaveBeenCalledWith("i1", "p1", {
      status: "later",
    })
    expect(document.querySelector(".writing-conflict-status").textContent).toBe("稍后")
  })

  it("groups rule hits and AI judgments", () => {
    showWritingConflictModal({
      check: {
        id: "c1",
        ai_review_status: "done",
        items: [
          {
            id: "i1",
            kind: "required_missing",
            severity: "medium",
            source_module: "outline",
            evidence_summary: "缺少令牌",
            status: "open",
          },
          {
            id: "i2",
            kind: "motivation_gap",
            severity: "medium",
            source_module: "ai",
            evidence_summary: "主角突然信任港务长",
            status: "open",
            is_ai_judgment: true,
            confidence: 0.72,
            llm_rationale: "缺少动机过渡",
          },
        ],
      },
      novelId: "p1",
    })

    const body = showModal.mock.calls[0][1]
    expect(body).toContain("规则命中")
    expect(body).toContain("AI 判断")
    expect(body).toContain("72%")
    expect(body).toContain("缺少动机过渡")
  })

  it("renders escaped structured evidence drawer and keeps source action", () => {
    showWritingConflictModal({
      check: {
        id: "c1",
        items: [
          {
            id: "i1",
            kind: "map_risk",
            severity: "medium",
            source_module: "world",
            evidence_summary: "<script>alert(1)</script>",
            status: "open",
            location_json: {
              source: {
                module: "world",
                label: "地图<script>alert(2)</script>",
                field: "location",
                type: "map_object",
                excerpt: "旧城<script>alert(3)</script>",
              },
              open_target: {
                kind: "map_object",
                object_id: "obj1",
              },
              needs_review_reason: "依赖待确认地图观察",
            },
          },
        ],
      },
      novelId: "p1",
    })

    const body = showModal.mock.calls[0][1]
    expect(body).toContain("writing-conflict-evidence-drawer")
    expect(body).toContain("&lt;script&gt;alert(1)&lt;/script&gt;")
    expect(body).toContain("地图&lt;script&gt;alert(2)&lt;/script&gt;")
    expect(body).toContain("旧城&lt;script&gt;alert(3)&lt;/script&gt;")
    expect(body).toContain("依赖待确认地图观察")
    expect(body).toContain("map_object")
    expect(body).toContain('data-conflict-open-source="i1"')
    expect(body).not.toContain("<script>")
  })

  it("uses precise include candidates copy without broad review wording", () => {
    showWritingConflictModal({
      check: {
        id: "c1",
        include_candidates: true,
        items: [],
      },
      novelId: "p1",
    })

    const body = showModal.mock.calls[0][1]
    expect(body).toContain("本次检查包含待确认对象")
    expect(body).not.toContain("结果需复核")
  })

  it("runs AI review after AI reference confirmation", async () => {
    confirmAiReference.mockResolvedValue({ id: "confirm-ai" })
    api.writing.runConflictAiReview.mockResolvedValue({
      id: "c1",
      ai_review_status: "done",
      items: [],
    })
    const onAiReviewComplete = vi.fn()
    showWritingConflictModal({
      check: {
        id: "c1",
        chapter_index: 1,
        scene_id: "scene-1",
        include_candidates: true,
        items: [],
      },
      novelId: "p1",
      onAiReviewComplete,
    })

    document.body.innerHTML = `<div>${showModal.mock.calls[0][1]}</div>`
    document.querySelector("[data-conflict-ai-review]").click()
    await Promise.resolve()
    await Promise.resolve()

    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      action: "writing.conflict_check.ai_review",
      context_mode: "canonical",
      scene_id: "scene-1",
      include_pending_objects: true,
    }))
    expect(api.writing.runConflictAiReview).toHaveBeenCalledWith("c1", {
      novel_id: "p1",
      context_confirmation_id: "confirm-ai",
    })
    expect(onAiReviewComplete).toHaveBeenCalled()
  })

  it("shows failed toast when AI review API returns failed status", async () => {
    confirmAiReference.mockResolvedValue({ id: "confirm-ai" })
    api.writing.runConflictAiReview.mockResolvedValue({
      id: "c1",
      ai_review_status: "failed",
      ai_review_error: "LLM timeout",
      items: [],
    })
    showWritingConflictModal({
      check: {
        id: "c1",
        chapter_index: 1,
        scene_id: "scene-1",
        items: [],
      },
      novelId: "p1",
      onAiReviewComplete: vi.fn(),
    })

    document.body.innerHTML = `<div>${showModal.mock.calls[0][1]}</div>`
    document.querySelector("[data-conflict-ai-review]").click()
    await Promise.resolve()
    await Promise.resolve()

    expect(toast).toHaveBeenCalledWith("LLM timeout", "error")
  })

  it("generates and renders escaped AI suggestion text", async () => {
    confirmAiReference.mockResolvedValue({ id: "confirm-suggest" })
    api.writing.requestConflictAiSuggestion.mockResolvedValue({
      id: "i1",
      suggestion_status: "done",
      ai_suggestion: JSON.stringify({
        strategy: "补动机",
        suggested_text: "<img src=x onerror=alert(1)>",
        rationale: "减少跳变",
        constraints: ["不能剧透"],
        risk_notes: ["需要作者确认"],
      }),
    })
    showWritingConflictModal({
      check: {
        id: "c1",
        chapter_index: 1,
        scene_id: "scene-1",
        items: [
          {
            id: "i1",
            kind: "required_missing",
            severity: "medium",
            source_module: "outline",
            evidence_summary: "缺少令牌",
            status: "open",
          },
        ],
      },
      novelId: "p1",
    })

    document.body.innerHTML = `<div>${showModal.mock.calls[0][1]}</div>`
    document.querySelector('[data-conflict-ai-suggestion="i1"]').click()
    await Promise.resolve()
    await Promise.resolve()

    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      action: "writing.conflict_check.ai_suggestion",
      context_mode: "canonical",
      scene_id: "scene-1",
    }))
    expect(api.writing.requestConflictAiSuggestion).toHaveBeenCalledWith("i1", {
      novel_id: "p1",
      context_confirmation_id: "confirm-suggest",
    })
    expect(document.body.innerHTML).toContain("&lt;img")
    expect(document.body.innerHTML).not.toContain("<img src=x")
    expect(document.body.textContent).toContain("补动机")
  })

  it("copies AI suggestion text and shows success toast", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    })

    showWritingConflictModal({
      check: {
        id: "c1",
        chapter_index: 1,
        scene_id: "scene-1",
        items: [
          {
            id: "i1",
            kind: "required_missing",
            severity: "medium",
            source_module: "ai",
            evidence_summary: "缺少动机",
            status: "open",
            ai_suggestion: JSON.stringify({
              strategy: "补动机",
              suggested_text: "在离开前补一段主角犹豫的心理描写。",
              rationale: "减少跳变",
            }),
          },
        ],
      },
      novelId: "p1",
    })

    document.body.innerHTML = `<div>${showModal.mock.calls[0][1]}</div>`
    document.querySelector('[data-conflict-copy-suggestion="i1"]').click()
    await Promise.resolve()

    expect(writeText).toHaveBeenCalledWith("在离开前补一段主角犹豫的心理描写。")
    expect(toast).toHaveBeenCalledWith("已复制 AI 修复建议", "success")
  })

  it("shows failed toast when AI suggestion API returns failed status", async () => {
    confirmAiReference.mockResolvedValue({ id: "confirm-suggest" })
    api.writing.requestConflictAiSuggestion.mockResolvedValue({
      id: "i1",
      suggestion_status: "failed",
      suggestion_error: "provider unavailable",
    })
    showWritingConflictModal({
      check: {
        id: "c1",
        chapter_index: 1,
        scene_id: "scene-1",
        items: [
          {
            id: "i1",
            kind: "required_missing",
            severity: "medium",
            source_module: "outline",
            evidence_summary: "缺少令牌",
            status: "open",
          },
        ],
      },
      novelId: "p1",
      onSuggestionComplete: vi.fn(),
    })

    document.body.innerHTML = `<div>${showModal.mock.calls[0][1]}</div>`
    document.querySelector('[data-conflict-ai-suggestion="i1"]').click()
    await Promise.resolve()
    await Promise.resolve()

    expect(toast).toHaveBeenCalledWith("provider unavailable", "error")
  })
})
