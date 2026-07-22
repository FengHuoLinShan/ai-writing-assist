import { beforeEach, describe, expect, it } from "vitest"
import {
  clearWritingSession,
  getWritingSession,
  readChapterSnapshot,
  rememberWritingLocation,
  rememberChapterSnapshot,
} from "../../../vue/views/writing/writingSession.js"

describe("writingSession", () => {
  beforeEach(() => clearWritingSession())

  it("按 project + chapter 隔离未保存正文", () => {
    rememberChapterSnapshot("p1", { chapter: 1, content: "甲", dirty: true })
    rememberChapterSnapshot("p2", { chapter: 1, content: "乙", dirty: true })
    expect(readChapterSnapshot("p1", 1).content).toBe("甲")
    expect(readChapterSnapshot("p2", 1).content).toBe("乙")
  })

  it("每个项目独立记忆最后章节", () => {
    rememberChapterSnapshot("p1", { chapter: 3, draftId: "d3" })
    rememberChapterSnapshot("p2", { chapter: 8, draftId: "d8" })
    expect(getWritingSession("p1")).toMatchObject({ currentChapter: 3, currentDraftId: "d3" })
    expect(getWritingSession("p2")).toMatchObject({ currentChapter: 8, currentDraftId: "d8" })
  })

  it("每个项目独立记忆当前 Scene", () => {
    rememberWritingLocation("p1", { currentChapter: 1, currentSceneId: "scene-p1" })
    rememberWritingLocation("p2", { currentChapter: 1, currentSceneId: "scene-p2" })
    expect(getWritingSession("p1").currentSceneId).toBe("scene-p1")
    expect(getWritingSession("p2").currentSceneId).toBe("scene-p2")
  })
})
