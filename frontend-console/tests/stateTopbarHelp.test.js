import { describe, it, expect, beforeEach } from "vitest"

import "../state.js"

describe("state topbar help", () => {
  beforeEach(() => {
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
