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
  const captured = captureWorkContext(state, null, "p1", "writing", editor, null, workspace)
  expect(captured.selection).toBe("乙丙")
  // R00：干净编辑器的选区带码点偏移（SourceRange 语义）。
  expect(captured.selection_start).toBe(1)
  expect(captured.selection_end).toBe(3)
  editor.closest(".vue-island").dataset.projectId = "p2"
  expect(captureWorkContext(state, null, "p1", "writing", editor, null, workspace).selection).toBe("")
})

it("counts selection offsets in code points, not UTF-16 units (emoji safe)", () => {
  document.body.innerHTML = '<div id="workspace-content"><div class="vue-island" data-project-id="p1"><textarea id="writing-editor"></textarea></div></div>'
  const editor = document.querySelector("textarea")
  // “甲😀乙”：😀 是增补平面字符，UTF-16 占 2 单位、码点 1 个。
  editor.value = "甲😀乙"
  editor.setSelectionRange(0, 4) // 选中整段（4 个 UTF-16 单位）
  const state = { currentProjectId: "p1", viewStates: { writing: { projectId: "p1" } } }
  const captured = captureWorkContext(state, null, "p1", "writing", editor, null, document.getElementById("workspace-content"))
  expect(captured.selection).toBe("甲😀乙")
  expect(captured.selection_start).toBe(0)
  expect(captured.selection_end).toBe(3) // 3 个码点，与服务端 len() 一致
})

it("omits selection offsets while the editor is dirty (saved draft would drift)", () => {
  document.body.innerHTML = '<div id="workspace-content"><div class="vue-island" data-project-id="p1"><textarea id="writing-editor"></textarea></div></div>'
  const editor = document.querySelector("textarea")
  editor.value = "甲乙丙丁"
  editor.setSelectionRange(1, 3)
  const state = {
    currentProjectId: "p1",
    viewStates: { writing: { projectId: "p1" } },
    _writingForecastState: { projectId: "p1", dirty: true },
  }
  const captured = captureWorkContext(state, null, "p1", "writing", editor, null, document.getElementById("workspace-content"))
  expect(captured.selection).toBe("乙丙") // 文本保留既有行为
  expect(captured.selection_start).toBeUndefined()
  expect(captured.selection_end).toBeUndefined()
})

it("never captures model credential fields as assistant input", () => {
  document.body.innerHTML = '<div id="workspace-content"><div class="vue-island" data-project-id="p1"><input type="password" value="synthetic-secret"></div></div>'
  const field = document.querySelector("input")
  field.setSelectionRange(0, 16)
  const result = captureWorkContext({ currentProjectId: "p1" }, null, "p1", "settings", field, null, document.getElementById("workspace-content"))
  expect(result.selection).toBe("")
})
