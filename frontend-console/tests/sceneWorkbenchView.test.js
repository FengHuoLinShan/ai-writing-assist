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
    {
      kind: "scene",
      health: [],
      chapter_range: "第 3 章",
      summary: "撤离王宫",
      scene: {
        id: "s2",
        scene_index: 1,
        title: "撤离",
        source: "manual",
        status: "draft",
        narrative_tag: "transition",
        chapter_ids: ["3"],
        goal: "带着密信撤离",
        core_conflict: "追兵封锁城门",
        emotional_beat: "压迫",
        must_happen: "密信被带出",
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
  api.outline.previewSceneFusion = vi.fn()
  api.outline.saveSceneFusion = vi.fn()
  api.outline.previewSceneMerge = vi.fn()
  api.outline.mergeScenes = vi.fn()
  api.outline.previewSceneSplit = vi.fn()
  api.outline.splitScene = vi.fn()
  api.outline.updateScene.mockResolvedValue({ id: "s1" })
  sceneWorkbenchView._loading = false
  sceneWorkbenchView._workbench = null
  sceneWorkbenchView._activeHealth = null
  sceneWorkbenchView._selectedFusionSceneIds = new Set()
})

describe("sceneWorkbenchView", () => {
  it("loads selected scene workbench data on enter", async () => {
    await sceneWorkbenchView.onEnter()

    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", "s1", {
      skip: 0,
      limit: 20,
    })
    expect(sceneWorkbenchView._workbench.items[0].scene.title).toBe("潜入")
  })

  it("applies management filters through scene workbench API params", async () => {
    api.outline.getSceneWorkbench.mockResolvedValue(workbenchPayload)
    document.body.innerHTML = `
      <select id="scene-filter-status"><option value="deprecated" selected>废弃</option></select>
      <select id="scene-filter-source"><option value="deep_import" selected>深度导入</option></select>
      <input id="scene-filter-workflow-id" value="wf-17" />
      <select id="scene-filter-needs-review"><option value="true" selected>需复核</option></select>
      <select id="scene-filter-boundary-status"><option value="uncertain" selected>边界不确定</option></select>
      <select id="scene-filter-phase"><option value="phase1a_fallback" selected>Phase 1A fallback</option></select>
      <label><input id="scene-filter-phase1a-fallback" type="checkbox" checked /> fallback</label>
    `

    await sceneWorkbenchView._applyManagementFilters()

    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith(
      "p1",
      "s1",
      expect.objectContaining({
        status: "deprecated",
        source: "deep_import",
        workflow_id: "wf-17",
        needs_review: true,
        boundary_status: "uncertain",
        phase: "phase1a_fallback",
        phase1a_fallback: true,
        skip: 0,
        limit: 20,
      }),
    )
    expect(sceneWorkbenchView._filters.status).toBe("deprecated")
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

  it("does not preview manual fusion with fewer than two selected scenes", async () => {
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1"])

    await sceneWorkbenchView._startManualFusion()

    expect(api.outline.previewSceneFusion).not.toHaveBeenCalled()
    expect(showModal).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("请至少选择 2 个 Scene 再融合", "warning")
  })

  it("previews manual fusion and shows editable fused fields", async () => {
    api.outline.previewSceneFusion.mockResolvedValue({
      source_scene_ids: ["s1", "s2"],
      fused_scene: {
        title: "潜入与撤离",
        goal: "取得密信并撤离",
        core_conflict: "守卫与追兵前后夹击",
        emotional_beat: "紧张升级",
        must_happen: "带出密信",
        must_not_happen: "暴露盟友",
        chapter_ids: ["1", "2", "3"],
      },
      preview_scene: { title: "预览 Scene" },
      warnings: ["章节跨度较大"],
    })
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1", "s2"])

    await sceneWorkbenchView._startManualFusion()

    expect(api.outline.previewSceneFusion).toHaveBeenCalledWith("p1", {
      source_scene_ids: ["s1", "s2"],
    })
    expect(showModal).toHaveBeenCalled()
    const [title, body, buttons] = showModal.mock.calls[0]
    expect(title).toBe("手动 Scene 融合")
    expect(body).toContain("潜入与撤离")
    expect(body).toContain("取得密信并撤离")
    expect(body).toContain("章节跨度较大")
    expect(body).toContain("scene-fusion-title")
    expect(buttons.map((button) => button.text)).toEqual([
      "保留原 Scene + 保存融合 Scene",
      "保存融合 Scene，并废弃原 Scene",
      "放弃融合结果",
      "继续编辑融合结果后再保存",
    ])
  })

  it.each([
    ["保留原 Scene + 保存融合 Scene", "keep_originals"],
    ["保存融合 Scene，并废弃原 Scene", "deprecate_originals"],
    ["放弃融合结果", "discard"],
  ])("calls fusion save mode %s and refreshes", async (buttonText, mode) => {
    api.outline.previewSceneFusion.mockResolvedValue({
      source_scene_ids: ["s1", "s2"],
      fused_scene: { title: "融合草稿", chapter_ids: ["1", "2", "3"] },
      preview_scene: {},
      warnings: [],
    })
    api.outline.saveSceneFusion.mockResolvedValue({ status: mode === "discard" ? "discarded" : "saved" })
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1", "s2"])

    await sceneWorkbenchView._startManualFusion()
    const buttons = showModal.mock.calls[0][2]
    await buttons.find((button) => button.text === buttonText).handler()

    expect(api.outline.saveSceneFusion).toHaveBeenCalledWith("p1", {
      source_scene_ids: ["s1", "s2"],
      mode,
    })
    expect(closeModal).toHaveBeenCalled()
    expect(router.refresh).toHaveBeenCalled()
  })

  it("saves edited manual fusion fields with edit_then_save and refreshes", async () => {
    api.outline.previewSceneFusion.mockResolvedValue({
      source_scene_ids: ["s1", "s2"],
      fused_scene: {
        title: "融合草稿",
        goal: "旧目标",
        core_conflict: "旧冲突",
        emotional_beat: "旧情绪",
        must_happen: "旧必须",
        must_not_happen: "旧禁止",
        chapter_ids: ["1", "2"],
      },
      preview_scene: {},
      warnings: [],
    })
    api.outline.saveSceneFusion.mockResolvedValue({ status: "saved" })
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1", "s2"])

    await sceneWorkbenchView._startManualFusion()
    const [, body, buttons] = showModal.mock.calls[0]
    document.body.innerHTML = body
    document.getElementById("scene-fusion-title").value = "用户改标题"
    document.getElementById("scene-fusion-goal").value = "用户改目标"
    document.getElementById("scene-fusion-conflict").value = "用户改冲突"
    document.getElementById("scene-fusion-emotion").value = "用户改情绪"
    document.getElementById("scene-fusion-must").value = "用户改必须"
    document.getElementById("scene-fusion-must-not").value = "用户改禁止"
    document.getElementById("scene-fusion-chapters").value = "5, 6"

    await buttons
      .find((button) => button.text === "继续编辑融合结果后再保存")
      .handler()

    expect(api.outline.saveSceneFusion).toHaveBeenCalledWith("p1", {
      source_scene_ids: ["s1", "s2"],
      mode: "edit_then_save",
      fused_scene: {
        title: "用户改标题",
        goal: "用户改目标",
        core_conflict: "用户改冲突",
        emotional_beat: "用户改情绪",
        must_happen: "用户改必须",
        must_not_happen: "用户改禁止",
        chapter_ids: ["5", "6"],
      },
    })
    expect(closeModal).toHaveBeenCalled()
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
