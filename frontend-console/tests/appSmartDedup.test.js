import { describe, it, expect, vi, beforeEach } from "vitest"
import App from "../app.js"
import { resetState, clearDocument } from "./helpers.js"

beforeEach(() => {
  resetState({ currentProjectId: "p1", currentView: "world" })
  clearDocument()
  document.body.innerHTML = '<div id="view-actions"></div>'
  App._smartDedupTaskId = null
  App._smartDedupProgress = null
  App._smartDedupPoller = null
  vi.clearAllMocks()
})

describe("App smart dedup action", () => {
  it("renders one global smart dedup button for active projects", () => {
    App._renderGlobalActions()

    const actions = document.getElementById("view-actions")
    expect(actions.innerHTML).toContain("智能去重")
    expect(actions.querySelectorAll('[data-action="start-smart-dedup"]')).toHaveLength(1)
  })

  it("does not render the smart dedup button on project list", () => {
    state.currentView = "project"

    App._renderGlobalActions()

    expect(document.getElementById("view-actions").innerHTML).toBe("")
  })

  it("escapes smart dedup suggestion text", () => {
    const html = App._renderSmartDedupSuggestion({
      asset_type: "plot_thread",
      action: "deprecate_duplicate",
      source_title: "<script>alert(1)</script>",
      target_title: "目标线",
      confidence: 0.9,
      reason: "<img src=x>",
      evidence_anchors: [{ snippet: "<b>证据</b>" }],
    }, 0)

    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;")
    expect(html).toContain("&lt;img src=x&gt;")
    expect(html).not.toContain("<script>alert(1)</script>")
  })

  it("applies selected smart dedup suggestions through project API", async () => {
    document.body.innerHTML = `
      <input type="checkbox" data-smart-dedup-index="0" checked />
      <div id="view-actions"></div>
    `
    api.projects.applySmartDedup.mockResolvedValue({ applied: 1, skipped: 0 })

    await App._applySmartDedupSuggestions([
      {
        asset_type: "plot_thread",
        action: "deprecate_duplicate",
        source_asset_id: "s1",
        target_asset_id: "t1",
        source_title: "来源",
      },
    ])

    expect(api.projects.applySmartDedup).toHaveBeenCalledWith("p1", {
      confirmed: true,
      suggestions: [
        {
          asset_type: "plot_thread",
          action: "deprecate_duplicate",
          source_asset_id: "s1",
          target_asset_id: "t1",
          alias: "来源",
          allow_canonical_merge: false,
        },
      ],
    })
    expect(closeModal).toHaveBeenCalled()
    expect(api.clearCache).toHaveBeenCalled()
    expect(router.refresh).toHaveBeenCalled()
  })
})
