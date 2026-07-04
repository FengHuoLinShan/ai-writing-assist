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
  App._smartDedupSuggestionPage = 0
  App._smartDedupSuggestionDraft = {}
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

  it("renders smart dedup suggestions with recommended primary controls and paginates the panel", () => {
    const suggestions = Array.from({ length: 8 }, (_, i) => ({
      asset_type: "world_entity",
      action: i === 0 ? "alias_only" : "merge",
      source_asset_id: `s${i + 1}`,
      source_title: `候选${i + 1}`,
      target_asset_id: `t${i + 1}`,
      target_title: `主体${i + 1}`,
      confidence: 0.9,
      reason: `原因${i + 1}`,
    }))

    App._smartDedupProgress = {
      done: true,
      raw: {
        result: {
          total_assets_scanned: 20,
          suggestion_count: suggestions.length,
          suggestions,
        },
      },
    }

    App._showSmartDedupSuggestions(0)

    const firstPageBody = showModal.mock.calls.at(-1)[1]
    expect(firstPageBody).toContain("第 1 / 2 页")
    expect(firstPageBody).toContain("候选1")
    expect(firstPageBody).toContain("主体对象")
    expect(firstPageBody).toContain("推荐主体")
    expect(firstPageBody).toContain("登记为别名")
    expect(firstPageBody).not.toContain("候选7")
  })

  it("uses the selected primary object when applying merge and alias suggestions", async () => {
    document.body.innerHTML = `
      <input type="checkbox" data-smart-dedup-index="0" checked />
      <input type="radio" name="smart-dedup-primary-0" value="source" checked />
      <input data-smart-dedup-manual-primary="0" value="" />
      <input type="checkbox" data-smart-dedup-index="1" checked />
      <input type="radio" name="smart-dedup-primary-1" value="manual" checked />
      <input data-smart-dedup-manual-primary="1" value="manual-primary" />
      <div id="view-actions"></div>
    `
    api.projects.applySmartDedup.mockResolvedValue({ applied: 2, skipped: 0 })

    await App._applySmartDedupSuggestions([
      {
        asset_type: "world_entity",
        action: "merge",
        source_asset_id: "candidate-id",
        source_title: "候选对象",
        target_asset_id: "canonical-id",
        target_title: "正史对象",
      },
      {
        asset_type: "world_entity",
        action: "alias_only",
        source_asset_id: "alias-source",
        source_title: "小名",
        target_asset_id: "alias-target",
        target_title: "主体对象",
      },
    ])

    expect(api.projects.applySmartDedup).toHaveBeenCalledWith("p1", {
      confirmed: true,
      suggestions: [
        {
          asset_type: "world_entity",
          action: "merge",
          source_asset_id: "canonical-id",
          target_asset_id: "candidate-id",
          alias: "正史对象",
          allow_canonical_merge: false,
        },
        {
          asset_type: "world_entity",
          action: "alias_only",
          source_asset_id: "alias-source",
          target_asset_id: "manual-primary",
          alias: "小名",
          allow_canonical_merge: false,
        },
      ],
    })
  })
})
