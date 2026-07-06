import { describe, it, expect, vi, beforeEach } from "vitest"
import App from "../app.js"
import { createSmartDedupManager } from "../shared/smartDedup.js"
import { resetState, clearDocument } from "./helpers.js"

beforeEach(() => {
  resetState({ currentProjectId: "p1", currentView: "world" })
  clearDocument()
  document.body.innerHTML = '<div id="view-actions"></div>'
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

  it("delegates start-smart-dedup action to the manager", () => {
    const startScan = vi.spyOn(App._smartDedup, "startScan").mockImplementation(() => {})

    App._renderGlobalActions()
    document.querySelector('[data-action="start-smart-dedup"]').click()

    expect(startScan).toHaveBeenCalled()
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

    expect(showProgress).toHaveBeenCalled()
    App._smartDedup.dispose()
  })
})
