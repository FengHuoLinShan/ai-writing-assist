import { describe, it, expect, vi, beforeEach } from "vitest"
import App from "../app.js"
import { createSmartDedupManager } from "../shared/smartDedup.js"
import { resetState, clearDocument } from "./helpers.js"

beforeEach(() => {
  resetState({ currentProjectId: "p1", currentView: "world" })
  clearDocument()
  document.body.innerHTML = `
    <main id="workspace">
      <div id="workspace-content">
        <span data-role="smart-dedup-action"></span>
      </div>
    </main>
  `
  App._smartDedup = createSmartDedupManager({
    api,
    router,
    toast,
    modal: { showModalHtml, closeModal },
    esc,
    onRenderActions: () => App._renderGlobalActions(),
    getCurrentProjectId: () => state.currentProjectId,
  })
  App._bindGlobalActions()
  localStorage.clear()
  vi.clearAllMocks()
})

describe("App smart dedup integration", () => {
  it("renders one local smart dedup button on the world page", () => {
    App._renderGlobalActions()

    const actions = document.querySelector('[data-role="smart-dedup-action"]')
    expect(actions.innerHTML).toContain("智能去重")
    expect(actions.querySelectorAll('[data-action="start-smart-dedup"]')).toHaveLength(1)
  })

  it.each(["project", "writing", "map", "rag", "generate", "settings", "project-settings"])(
    "does not render the smart dedup button on %s",
    (viewName) => {
      state.currentView = viewName

      App._renderGlobalActions()

      expect(document.querySelector('[data-role="smart-dedup-action"]').innerHTML).toBe("")
    },
  )

  it("renders the smart dedup button in an outline-local mount", () => {
    state.currentView = "outline"
    state.currentSubView = "scenes"

    App._renderGlobalActions()

    expect(document.querySelectorAll('[data-action="start-smart-dedup"]')).toHaveLength(1)
  })

  it("delegates start-smart-dedup action to the manager", () => {
    const startScan = vi.spyOn(App._smartDedup, "startScan").mockImplementation(() => {})

    App._renderGlobalActions()
    document.querySelector('[data-action="start-smart-dedup"]').click()

    expect(startScan).toHaveBeenCalledTimes(1)
  })

  it("repaints exactly one action after a local workspace rerender", () => {
    App._renderGlobalActions()
    const content = document.getElementById("workspace-content")
    content.innerHTML = '<span data-role="smart-dedup-action"></span>'

    content.dispatchEvent(new Event("workspace:content-rendered", { bubbles: true }))

    expect(content.querySelectorAll('[data-action="start-smart-dedup"]')).toHaveLength(1)
  })

  it("delegates show-smart-dedup-progress action to the manager", async () => {
    const showProgress = vi.spyOn(App._smartDedup, "showProgress").mockImplementation(() => {})
    api.projects.startSmartDedupScan.mockResolvedValue({ task_id: "scan-1" })
    api.tasks.get.mockResolvedValue({
      task_id: "scan-1",
      task_type: "smart_dedup_scan",
      status: "running",
    })

    await App._smartDedup.startScan()
    App._renderGlobalActions()
    document.querySelector('[data-action="show-smart-dedup-progress"]').click()

    expect(showProgress).toHaveBeenCalledTimes(1)
    App._smartDedup.dispose()
  })
})
