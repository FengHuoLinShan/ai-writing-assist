/**
 * writingToolsResult 最小测试
 */
import { describe, it, expect } from "vitest"
import { applyToolsResult } from "../../shared/writingToolsResult.js"

describe("applyToolsResult", () => {
  it("opens a generated candidate as a readonly chapter version", () => {
    const action = applyToolsResult(
      { chapter_index: 7, draft_id: "candidate-7" },
      { _scenes: [], _chapters: {}, _chapterList: [7] },
    )

    expect(action).toEqual({
      selectChapter: 7,
      selectOptions: { draftId: "candidate-7", isReadonly: true },
    })
  })

  it("selects new chapter when split result contains new_chapter_index", () => {
    const view = {
      _scenes: [],
      _chapters: { 1: { title: "源章", draftCount: 1 } },
      _chapterList: [1],
    }
    const result = {
      new_chapter_index: 2,
      source_chapter_index: 1,
      scenes: [{ id: "s2" }],
      source_draft: { title: "源章" },
      new_draft: { title: "新章" },
    }

    const action = applyToolsResult(result, view)

    expect(action).toEqual({ selectChapter: 2 })
    expect(view._chapterList).toEqual([1, 2])
    expect(view._chapters[1].draftCount).toBe(2)
    expect(view._chapters[2]).toEqual({ title: "新章", draftCount: 1 })
    expect(view._scenes).toEqual([{ id: "s2" }])
  })

  it("replaces scenes and requests rerender when result is an array", () => {
    const view = {
      _scenes: [],
      _chapters: {},
      _chapterList: [],
    }
    const result = [{ id: "s1" }, { id: "s2" }]

    const action = applyToolsResult(result, view)

    expect(action).toEqual({ rerender: true })
    expect(view._scenes).toEqual([{ id: "s1" }, { id: "s2" }])
  })

  it("returns empty action for unrecognized result", () => {
    const view = {
      _scenes: [],
      _chapters: {},
      _chapterList: [],
    }
    const action = applyToolsResult({ unknown: true }, view)
    expect(action).toEqual({})
  })

  it("keeps chapter list sorted after adding new chapter", () => {
    const view = {
      _scenes: [],
      _chapters: { 1: { title: "第一章" } },
      _chapterList: [3, 1],
    }
    const result = {
      new_chapter_index: 2,
      source_chapter_index: 1,
      source_draft: { title: "第一章" },
      new_draft: { title: "第二章" },
    }

    applyToolsResult(result, view)
    expect(view._chapterList).toEqual([1, 2, 3])
  })
})
