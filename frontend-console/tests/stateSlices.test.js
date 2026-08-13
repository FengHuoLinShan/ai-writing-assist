import { beforeEach, describe, expect, it } from "vitest"

import "../stateSlices.js"

const {
  applyStateSideEffects,
  projectStorageSummary,
} = globalThis.stateSlices

describe("stateSlices", () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it("keeps only storage-safe project summary fields", () => {
    expect(projectStorageSummary(null)).toBeNull()
    expect(projectStorageSummary({ genre: "fantasy" })).toBeNull()
    expect(projectStorageSummary({
      id: "project-1",
      title: "第一本书",
      name: "旧名",
      secret: "不应持久化",
    })).toEqual({
      id: "project-1",
      title: "第一本书",
      name: "旧名",
    })
  })

  it("cleans writing view state and persists currentProjectId on project switch", () => {
    const target = {
      viewStates: {
        writing: { projectId: "old-project", currentChapter: 3 },
        outline: { selectedThreadId: "thread-1" },
      },
    }

    applyStateSideEffects({
      key: "currentProjectId",
      value: "project-1",
      oldValue: "old-project",
      target,
    })

    expect(target.viewStates.writing).toBeUndefined()
    expect(target.viewStates.outline).toEqual({ selectedThreadId: "thread-1" })
    expect(localStorage.getItem("novel_currentProjectId")).toBe("project-1")

    applyStateSideEffects({
      key: "currentProjectId",
      value: null,
      oldValue: "project-1",
      target,
    })

    expect(localStorage.getItem("novel_currentProjectId")).toBeNull()
  })

  it("persists and clears currentProject summary", () => {
    const target = { viewStates: {} }

    applyStateSideEffects({
      key: "currentProject",
      value: { id: "project-1", title: "第一本书", name: "旧名", genre: "fantasy" },
      oldValue: null,
      target,
    })

    expect(JSON.parse(localStorage.getItem("novel_currentProject"))).toEqual({
      id: "project-1",
      title: "第一本书",
      name: "旧名",
    })

    applyStateSideEffects({
      key: "currentProject",
      value: null,
      oldValue: { id: "project-1" },
      target,
    })

    expect(localStorage.getItem("novel_currentProject")).toBeNull()
  })

})
