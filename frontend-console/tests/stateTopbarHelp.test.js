import { beforeEach, describe, expect, it, vi } from "vitest"

import "../stateSlices.js"
import "../state.js"

function resetState() {
  localStorage.clear()
  window.appState.currentProjectId = null
  window.appState.currentProject = null
  window.appState.viewStates = {}
}

describe("state project persistence", () => {
  beforeEach(() => {
    resetState()
    document.body.innerHTML = ""
  })

  it("persists project ids and drops writing view state on project changes", () => {
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

  it("persists only the safe project summary and clears it", () => {
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
    expect(JSON.parse(localStorage.getItem("novel_currentProject"))).toEqual({
      id: "project-1",
      title: "第一本书",
      name: "旧名",
    })

    window.appState.currentProject = null
    expect(localStorage.getItem("novel_currentProject")).toBeNull()
  })

  it("continues notifying subscribers after one listener fails", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {})
    const observed = []
    const unsubscribeFailing = window.onStateChange((key) => {
      if (key === "currentProject") throw new Error("listener failed")
    })
    const unsubscribeObserved = window.onStateChange((key, value, oldValue) => {
      if (key === "currentProject") observed.push({ title: value.title, oldValue })
    })

    try {
      window.appState.currentProject = { id: "project-1", title: "新项目" }
      expect(consoleError).toHaveBeenCalledWith("State listener error:", expect.any(Error))
    } finally {
      unsubscribeFailing()
      unsubscribeObserved()
      consoleError.mockRestore()
    }

    expect(observed).toEqual([{ title: "新项目", oldValue: null }])
    expect(JSON.parse(localStorage.getItem("novel_currentProject"))).toEqual({
      id: "project-1",
      title: "新项目",
    })
  })
})
