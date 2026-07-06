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
