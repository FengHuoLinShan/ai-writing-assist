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
    rememberChapterSnapshot("p1", {
      chapter: 3,
      draftId: "d3",
      versionNumber: 7,
      updatedAt: "2026-08-18T10:00:00Z",
      content: "本地正文",
      cursorOffset: 99,
      dirty: true,
    })
    forgetWritingSessionMemory("p1")

    expect(readWritingPointer("p1")).toMatchObject({
      projectId: "p1",
      chapter: 3,
      draftId: "d3",
      draftVersion: 7,
      draftUpdatedAt: "2026-08-18T10:00:00Z",
      sceneId: "s3",
      cursorOffset: 99,
    })
    expect(readWritingPointer("p1").pointerUpdatedAt).toBeGreaterThan(0)
    expect(getWritingSession("p1")).toMatchObject({ currentChapter: 3, currentDraftId: "d3", currentSceneId: "s3" })
    expect(localStorage.getItem("writing_resume_pointer:v1:p1")).not.toContain("本地正文")
  })

  it("按项目记忆手机完整编辑模式", () => {
    rememberWritingLocation("p1", { currentChapter: 1, completeEditor: true })
    rememberWritingLocation("p2", { currentChapter: 1, completeEditor: false })
    forgetWritingSessionMemory()

    expect(getWritingSession("p1").completeEditor).toBe(true)
    expect(getWritingSession("p2").completeEditor).toBe(false)
  })

  it("按项目记忆专注模式，并保留未选择过时的默认态", () => {
    expect(getWritingSession("fresh").focusMode).toBeNull()
    rememberWritingLocation("p1", { currentChapter: 1, focusMode: true })
    rememberWritingLocation("p2", { currentChapter: 1, focusMode: false })
    forgetWritingSessionMemory()

    expect(getWritingSession("p1").focusMode).toBe(true)
    expect(getWritingSession("p2").focusMode).toBe(false)
  })

  it("每项目只保留当前章与最近四章", () => {
    for (let chapter = 1; chapter <= 6; chapter += 1) {
      rememberChapterSnapshot("p1", { chapter, content: `第${chapter}章` })
    }

    expect(readChapterSnapshot("p1", 1)).toBeNull()
    expect(readChapterSnapshot("p1", 2).content).toBe("第2章")
    expect(getWritingSession("p1").currentChapter).toBe(6)
  })

  it("不淘汰尚未完成备份的 dirty 章节", () => {
    rememberChapterSnapshot("p1", { chapter: 1, content: "未备份", dirty: true })
    for (let chapter = 2; chapter <= 6; chapter += 1) {
      rememberChapterSnapshot("p1", { chapter, content: `第${chapter}章` })
    }

    expect(readChapterSnapshot("p1", 1).content).toBe("未备份")
    expect(readChapterSnapshot("p1", 2)).toBeNull()
  })

  it("最多保留五个最近项目", () => {
    for (let project = 1; project <= 6; project += 1) {
      rememberChapterSnapshot(`p${project}`, { chapter: 1, content: `项目${project}` })
    }

    expect(readChapterSnapshot("p1", 1)).toBeNull()
    expect(readChapterSnapshot("p6", 1).content).toBe("项目6")
  })

  it("项目 LRU 也保留尚未完成备份的 dirty 会话", () => {
    rememberChapterSnapshot("p1", { chapter: 1, content: "未备份", dirty: true })
    for (let project = 2; project <= 6; project += 1) {
      rememberChapterSnapshot(`p${project}`, { chapter: 1, content: `项目${project}` })
    }

    expect(readChapterSnapshot("p1", 1).content).toBe("未备份")
    expect(readChapterSnapshot("p2", 1)).toBeNull()
    expect(readChapterSnapshot("p6", 1).content).toBe("项目6")
  })
})
