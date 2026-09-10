import { afterEach, expect, it } from "vitest"
import { captureWorkContext } from "../../../vue/shared/assistantContext.js"

afterEach(() => { document.body.innerHTML = "" })

it("captures an explicit writing selection only from the matching project DOM", () => {
  document.body.innerHTML = '<div id="workspace-content"><div class="vue-island" data-project-id="p1"><textarea id="writing-editor"></textarea></div></div>'
  const editor = document.querySelector("textarea")
  editor.value = "甲乙丙丁"
  editor.setSelectionRange(1, 3)
  const state = { currentProjectId: "p1", viewStates: { writing: { projectId: "p1" } }, _currentChapter: 3 }
  const workspace = document.getElementById("workspace-content")
  expect(captureWorkContext(state, null, "p1", "writing", editor, null, workspace).selection).toBe("乙丙")
  editor.closest(".vue-island").dataset.projectId = "p2"
  expect(captureWorkContext(state, null, "p1", "writing", editor, null, workspace).selection).toBe("")
})

it("never captures model credential fields as assistant input", () => {
  document.body.innerHTML = '<div id="workspace-content"><div class="vue-island" data-project-id="p1"><input type="password" value="synthetic-secret"></div></div>'
  const field = document.querySelector("input")
  field.setSelectionRange(0, 16)
  const result = captureWorkContext({ currentProjectId: "p1" }, null, "p1", "settings", field, null, document.getElementById("workspace-content"))
  expect(result.selection).toBe("")
})
