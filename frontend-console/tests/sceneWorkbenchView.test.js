import { beforeEach, describe, expect, it, vi } from "vitest"

import sceneWorkbenchView from "../views/sceneWorkbenchView.js"
import { clearDocument, resetState } from "./helpers.js"

const workbenchPayload = {
  health: {
    unreviewed: { key: "unreviewed", label: "未复核", count: 1 },
    unassigned: { key: "unassigned", label: "未关联章节", count: 1 },
    missing_setup: { key: "missing_setup", label: "缺设定", count: 1 },
    needs_organize: { key: "needs_organize", label: "待整理", count: 1 },
  },
  unassigned_chapters: [4],
  selected_scene_id: "s1",
  items: [
    {
      kind: "scene",
      health: ["unreviewed", "missing_setup"],
      chapter_range: "第 1-2 章",
      summary: "潜入王宫",
      scene: {
        id: "s1",
        scene_index: 0,
        title: "潜入",
        source: "deep_import",
        status: "draft",
        narrative_tag: "rising_action",
        chapter_ids: ["1", "2"],
        goal: "潜入王宫",
        core_conflict: "",
        emotional_beat: "紧张",
        must_happen: "",
        must_not_happen: "",
        pov_character_id: "char-1",
        structure_meta: {},
      },
    },
  ],
}

beforeEach(() => {
  resetState({ currentProjectId: "p1", currentSubView: "s1" })
  clearDocument()
  vi.clearAllMocks()
  api.outline.getSceneWorkbench = vi.fn().mockResolvedValue(workbenchPayload)
  api.outline.updateSceneWorkbenchMapping = vi.fn()
  api.outline.previewSceneMerge = vi.fn()
  api.outline.mergeScenes = vi.fn()
  api.outline.previewSceneSplit = vi.fn()
  api.outline.splitScene = vi.fn()
  api.outline.updateScene.mockResolvedValue({ id: "s1" })
  sceneWorkbenchView._loading = false
  sceneWorkbenchView._workbench = null
  sceneWorkbenchView._activeHealth = null
})

describe("sceneWorkbenchView", () => {
  it("loads selected scene workbench data on enter", async () => {
    await sceneWorkbenchView.onEnter()

    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", "s1")
    expect(sceneWorkbenchView._workbench.items[0].scene.title).toBe("潜入")
  })

  it("renders fixed health filters, 62/38 desktop layout, and unassigned chapters", async () => {
    sceneWorkbenchView._workbench = workbenchPayload

    const html = await sceneWorkbenchView.render()

    expect(html).toContain("scene-workbench")
    expect(html).toContain("scene-workbench__organize")
    expect(html).toContain("scene-workbench__detail")
    expect(html).toContain("未复核")
    expect(html).toContain("未关联章节")
    expect(html).toContain("缺设定")
    expect(html).toContain("待整理")
    expect(html).toContain("潜入")
    expect(html).toContain("第 4 章")
    expect(html).toContain("data-action=\"assign-unassigned-chapter\"")
  })

  it("filters scene list by health key", async () => {
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      items: [
        ...workbenchPayload.items,
        {
          kind: "scene",
          health: ["needs_organize"],
          chapter_range: "第 3 章",
          scene: { id: "s2", scene_index: 1, title: "整理项", status: "draft" },
        },
      ],
    }
    sceneWorkbenchView._activeHealth = "needs_organize"

    const html = await sceneWorkbenchView.render()

    expect(html).toContain("整理项")
    expect(html).not.toContain("潜入")
  })

  it("renders detail as drawer markup on narrow screens", async () => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(390)
    sceneWorkbenchView._workbench = workbenchPayload

    const html = await sceneWorkbenchView.render()

    expect(html).toContain("scene-workbench-drawer")
    expect(html).toContain("data-action=\"close-scene-detail\"")
  })

  it("saves editable scene fields through outline updateScene", async () => {
    document.body.innerHTML = `
      <input id="scene-detail-title" value="新标题" />
      <select id="scene-detail-tag"><option value="climax" selected>climax</option></select>
      <select id="scene-detail-status"><option value="canonical" selected>canonical</option></select>
      <select id="scene-detail-source"><option value="manual" selected>manual</option></select>
      <textarea id="scene-detail-goal">目标</textarea>
      <textarea id="scene-detail-conflict">冲突</textarea>
      <textarea id="scene-detail-emotion">情感</textarea>
      <textarea id="scene-detail-must">必须</textarea>
      <textarea id="scene-detail-must-not">禁止</textarea>
      <input id="scene-detail-pov" value="char-2" />
    `
    sceneWorkbenchView._workbench = workbenchPayload

    await sceneWorkbenchView._saveSceneDetails("s1")

    expect(api.outline.updateScene).toHaveBeenCalledWith("s1", "p1", {
      title: "新标题",
      narrative_tag: "climax",
      status: "canonical",
      source: "manual",
      goal: "目标",
      core_conflict: "冲突",
      emotional_beat: "情感",
      must_happen: "必须",
      must_not_happen: "禁止",
      pov_character_id: "char-2",
    })
    expect(router.refresh).toHaveBeenCalled()
  })

  it("shows merge preview before calling merge", async () => {
    api.outline.previewSceneMerge.mockResolvedValue({
      operation: "merge",
      chapter_mapping_change: { after: { s1: ["1", "2"] } },
      field_changes: {},
      warnings: ["只提示"],
    })
    api.outline.mergeScenes.mockResolvedValue({ scene: { id: "s1" } })
    showModal.mockImplementation((_title, _body, buttons) => buttons[1].handler())
    sceneWorkbenchView._workbench = workbenchPayload

    await sceneWorkbenchView._previewAndMerge("s1", ["s2"])

    expect(api.outline.previewSceneMerge).toHaveBeenCalledWith("p1", {
      target_scene_id: "s1",
      source_scene_ids: ["s2"],
    })
    expect(showModal).toHaveBeenCalled()
    expect(api.outline.mergeScenes).toHaveBeenCalledWith("p1", {
      target_scene_id: "s1",
      source_scene_ids: ["s2"],
      confirmed: true,
    })
  })

  it("opens writing at the first mapped chapter", () => {
    sceneWorkbenchView._openWritingForScene({
      id: "s1",
      chapter_ids: ["3", "4"],
    })

    expect(state.viewStates.writing.currentChapter).toBe(3)
    expect(router.navigate).toHaveBeenCalledWith("writing", null)
  })
})
