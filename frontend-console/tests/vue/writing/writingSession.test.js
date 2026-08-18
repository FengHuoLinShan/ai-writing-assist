import { beforeEach, describe, expect, it } from "vitest"
import {
  clearWritingSession,
  forgetWritingSessionMemory,
  getWritingSession,
  rememberedSceneForChapter,
  readChapterSnapshot,
  rememberWritingLocation,
  rememberChapterSnapshot,
  readWritingPointer,
} from "../../../vue/views/writing/writingSession.js"

describe("writingSession", () => {
  beforeEach(() => {
    localStorage.clear()
    clearWritingSession()
  })

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

  it("按项目和章节记忆作者手选 Scene", () => {
    rememberWritingLocation("p1", { currentChapter: 1, currentSceneId: "scene-1" })
    rememberWritingLocation("p1", { currentChapter: 2, currentSceneId: "scene-2" })
    rememberWritingLocation("p2", { currentChapter: 1, currentSceneId: "scene-p2" })
    expect(rememberedSceneForChapter("p1", 1)).toBe("scene-1")
    expect(rememberedSceneForChapter("p1", 2)).toBe("scene-2")
    expect(rememberedSceneForChapter("p2", 1)).toBe("scene-p2")
  })

  it("只持久化安全恢复指针并可跨页面重读", () => {
    rememberWritingLocation("p1", { currentChapter: 3, currentDraftId: "d3", currentSceneId: "s3" })
    rememberChapterSnapshot("p1", { chapter: 3, draftId: "d3", content: "本地正文", cursorOffset: 99, dirty: true })
    forgetWritingSessionMemory("p1")

    expect(readWritingPointer("p1")).toMatchObject({
      projectId: "p1", chapter: 3, draftId: "d3", sceneId: "s3", cursorOffset: 99,
    })
    expect(getWritingSession("p1")).toMatchObject({ currentChapter: 3, currentDraftId: "d3", currentSceneId: "s3" })
    expect(localStorage.getItem("writing_resume_pointer:v1:p1")).not.toContain("本地正文")
  })
})
