import { describe, it, expect, beforeEach, vi } from "vitest"

import "../stateSlices.js"
import "../state.js"

function resetState() {
  localStorage.clear()
  window.appState.currentProjectId = null
  window.appState.currentProject = null
  window.appState.viewStates = {}
}

describe("state topbar help", () => {
  beforeEach(() => {
    resetState()
    document.body.innerHTML = `
      <div class="topbar-center">
        <span id="topbar-module">写作台</span>
      </div>
      <aside id="contextual-notes">
        <div class="note-card">旧帮助</div>
      </aside>
    `
  })

  it("moves route help copy to the topbar and clears the right help rail", () => {
    window.updateRightPanelForView("writing")

    expect(document.getElementById("contextual-notes")?.innerHTML).toBe("")
    expect(document.getElementById("topbar-view-note")?.textContent).toBe(
      "按章节撰写正文。支持暂存、发布、版本管理。",
    )
  })

  it("removes route help when the view has no migrated help copy", () => {
    window.updateRightPanelForView("writing")
    window.updateRightPanelForView("generate")

    expect(document.getElementById("topbar-view-note")).toBeNull()
    expect(document.getElementById("contextual-notes")?.innerHTML).toBe("")
  })
})

describe("state mode styling", () => {
  beforeEach(() => {
    resetState()
    document.body.innerHTML = `
      <span id="command-mode" class="command-mode-label"></span>
      <input id="command-input" />
    `
  })

  it("sets command class on COMMAND mode", () => {
    window.appState.mode = "COMMAND"
    expect(document.getElementById("command-mode").className).toBe("command-mode-label command")
  })

  it("sets search class on SEARCH mode", () => {
    window.appState.mode = "SEARCH"
    expect(document.getElementById("command-mode").className).toBe("command-mode-label search")
  })

  it("resets mode label class to default on NORMAL mode", () => {
    window.appState.mode = "COMMAND"
    expect(document.getElementById("command-mode").className).toBe("command-mode-label command")

    window.appState.mode = "NORMAL"
    expect(document.getElementById("command-mode").className).toBe("command-mode-label")
  })
})

describe("state project persistence", () => {
  beforeEach(() => {
    resetState()
    document.body.innerHTML = ""
  })

  it("persists and clears currentProjectId and drops writing view state on project changes", () => {
    window.appState.viewStates = {
      writing: { projectId: "old-project", currentChapter: 3 },
      outline: { selectedThreadId: "thread-1" },
    }

    window.appState.currentProjectId = "project-1"

    expect(localStorage.getItem("novel_currentProjectId")).toBe("project-1")
    expect(window.appState.viewStates.writing).toBeUndefined()
    expect(window.appState.viewStates.outline).toEqual({ selectedThreadId: "thread-1" })

    window.appState.viewStates.writing = { projectId: "project-1", currentChapter: 1 }
    window.appState.currentProjectId = "project-2"

    expect(localStorage.getItem("novel_currentProjectId")).toBe("project-2")
    expect(window.appState.viewStates.writing).toBeUndefined()

    window.appState.currentProjectId = null

    expect(localStorage.getItem("novel_currentProjectId")).toBeNull()
  })

  it("persists and clears currentProject", () => {
    const project = {
      id: "project-1",
      title: "第一本书",
      name: "旧名",
      genre: "fantasy",
      tone: "冷峻",
      current_stage: "writing",
      target_length: "epic",
      updated_at: "2026-07-07T00:00:00Z",
    }

    window.appState.currentProject = project

    expect(window.appState.currentProject).toEqual(project)
    expect(JSON.parse(localStorage.getItem("novel_currentProject"))).toEqual({
      id: "project-1",
      title: "第一本书",
      name: "旧名",
    })

    window.appState.currentProject = null

    expect(localStorage.getItem("novel_currentProject")).toBeNull()
  })

  it("notifies listeners before DOM sync and still syncs DOM after listener errors", () => {
    document.body.innerHTML = '<span id="topbar-project">旧项目</span>'
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {})
    const observed = []
    const unsubscribe = window.onStateChange((key, value, oldValue) => {
      if (key !== "currentProject") return
      observed.push({
        domText: document.getElementById("topbar-project").textContent,
        title: value.title,
        oldValue,
      })
      throw new Error("listener failed")
    })

    try {
      window.appState.currentProject = { id: "project-1", title: "新项目" }
      expect(consoleError).toHaveBeenCalledWith("State listener error:", expect.any(Error))
    } finally {
      unsubscribe()
      consoleError.mockRestore()
    }

    expect(observed).toEqual([
      {
        domText: "旧项目",
        title: "新项目",
        oldValue: null,
      },
    ])
    expect(document.getElementById("topbar-project").textContent).toBe("新项目")
  })
})
