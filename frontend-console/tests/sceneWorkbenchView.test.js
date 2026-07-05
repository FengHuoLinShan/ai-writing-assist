import { beforeEach, describe, expect, it, vi } from "vitest"

import sceneWorkbenchView from "../views/sceneWorkbenchView.js"
import { captureModalHandler, clearDocument, resetState } from "./helpers.js"

const workbenchPayload = {
  total: 2,
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
  vi.restoreAllMocks()
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
  sceneWorkbenchView._total = 0
  sceneWorkbenchView._activeHealth = null
  sceneWorkbenchView._filters = {
    status: "",
    source: "",
    workflow_id: "",
    needs_review: "",
    boundary_status: "",
    phase: "",
    phase1a_fallback: false,
    skip: 0,
    limit: 20,
  }
  sceneWorkbenchView._advancedFiltersOpen = false
  sceneWorkbenchView._selectedFusionSceneIds = new Set()
  sceneWorkbenchView._autoExtractTaskId = null
  sceneWorkbenchView._autoExtractProgress = null
  sceneWorkbenchView._autoExtractPoller = null
  sceneWorkbenchView._autoExtractMeta = null
  sceneWorkbenchView._mobileDetailOpen = false
})

describe("sceneWorkbenchView", () => {
  it("renders scene auto extraction action", async () => {
    sceneWorkbenchView._workbench = workbenchPayload

    const html = await sceneWorkbenchView.render()

    expect(html).toContain("场景（scene）自动提取")
    expect(html).toContain('data-action="scene-auto-extract"')
    expect(html).toContain("再选 2 个即可融合")
    expect(html).toContain('data-action="start-selected-merge"')
    expect(html).toContain("机械合并")
    expect(html).toContain('data-action="start-ai-fusion-draft"')
    expect(html).toContain("AI 融合草稿")
    expect(html).toContain("拆分/整理")
    expect(html).not.toContain(">整理</button>")
  })

  it("selects visible scenes for manual fusion", () => {
    sceneWorkbenchView._workbench = workbenchPayload

    sceneWorkbenchView._selectVisibleFusionScenes()

    expect(sceneWorkbenchView._selectedFusionSceneIds).toEqual(new Set(["s1", "s2"]))
    expect(router.renderCurrentView).not.toHaveBeenCalled()
  })

  it("toggles fusion selection without rerendering the whole scene page", async () => {
    state.currentView = "scene"
    sceneWorkbenchView._workbench = workbenchPayload
    document.body.innerHTML = `<main id="workspace-content">${await sceneWorkbenchView.render()}</main>`
    sceneWorkbenchView._bindEvents()
    vi.clearAllMocks()

    document.querySelector('.scene-workbench-row[data-id="s2"] input[data-action="toggle-fusion-selection"]').click()

    expect(sceneWorkbenchView._selectedFusionSceneIds).toEqual(new Set(["s2"]))
    expect(router.renderCurrentView).not.toHaveBeenCalled()
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("submits scene auto extraction stage task", async () => {
    api.imports.startStage.mockResolvedValue({ task_id: "scene-task" })
    sceneWorkbenchView._showSceneAutoExtractForm()
    document.body.innerHTML += `
      <input id="scene-auto-extract-start" value="1" />
      <input id="scene-auto-extract-end" value="5" />
    `

    await captureModalHandler()()

    expect(api.imports.startStage).toHaveBeenCalledWith("scenes", "p1", 1, 5)
    expect(toast).toHaveBeenCalledWith(
      "场景（scene）自动提取任务已提交：scene-task",
      "success",
    )
  })

  it("loads selected scene workbench data on enter", async () => {
    await sceneWorkbenchView.onEnter()

    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", "s1", {
      skip: 0,
      limit: 20,
    })
    expect(sceneWorkbenchView._workbench.items[0].scene.title).toBe("潜入")
    expect(sceneWorkbenchView._total).toBe(2)
  })

  it("renders pagination when scene workbench has more than one page", async () => {
    sceneWorkbenchView._workbench = { ...workbenchPayload, total: 45 }
    sceneWorkbenchView._total = 45

    const html = await sceneWorkbenchView.render()

    expect(html).toContain('data-action="prev-scene-page"')
    expect(html).toContain('data-action="next-scene-page"')
    expect(html).toContain('class="scene-workbench-pagination"')
    expect(html).toContain("共 45 条")
  })

  it("changes scene page through workbench API params", async () => {
    sceneWorkbenchView._workbench = { ...workbenchPayload, total: 45 }
    sceneWorkbenchView._total = 45
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1", "s2"])

    await sceneWorkbenchView._changePage(1)

    expect(sceneWorkbenchView._filters.skip).toBe(20)
    expect(sceneWorkbenchView._selectedFusionSceneIds.size).toBe(0)
    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", "s1", {
      skip: 20,
      limit: 20,
    })
    expect(router.refresh).toHaveBeenCalled()
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
    sceneWorkbenchView._mobileDetailOpen = true

    const html = await sceneWorkbenchView.render()

    expect(html).toContain("scene-workbench-drawer")
    expect(html).toContain("data-action=\"close-scene-detail\"")
  })

  it("renders scene review actions in row and detail", async () => {
    sceneWorkbenchView._workbench = workbenchPayload

    const html = await sceneWorkbenchView.render()

    expect(html).toContain('data-action="mark-scene-reviewed"')
    expect(html).toContain("复核通过")
    expect(html).toContain("来源与复核")
    expect(html).toContain("未复核")
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

  it("marks a scene as reviewed while preserving structure meta", async () => {
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      items: workbenchPayload.items.map((item) => item.scene.id === "s1"
        ? {
            ...item,
            scene: {
              ...item.scene,
              structure_meta: { source_workflow_id: "wf-1", needs_review: true },
            },
          }
        : item),
    }

    await sceneWorkbenchView._markSceneReviewed("s1")

    expect(api.outline.updateScene).toHaveBeenCalledWith("s1", "p1", {
      structure_meta: expect.objectContaining({
        source_workflow_id: "wf-1",
        needs_review: false,
        reviewed_at: expect.any(String),
        reviewed_by: "manual",
        reviewed_from: "scene_workbench",
      }),
    })
    expect(toast).toHaveBeenCalledWith("Scene 已标记为已复核", "success")
    expect(router.refresh).toHaveBeenCalled()
  })

  it("marks a reviewed scene as needing review", async () => {
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      items: workbenchPayload.items.map((item) => item.scene.id === "s1"
        ? {
            ...item,
            scene: {
              ...item.scene,
              structure_meta: {
                source_workflow_id: "wf-1",
                reviewed_at: "2026-07-05T00:00:00.000Z",
                reviewed_by: "manual",
                reviewed_from: "scene_workbench",
              },
            },
          }
        : item),
    }

    await sceneWorkbenchView._markSceneUnreviewed("s1")

    const payload = api.outline.updateScene.mock.calls[0][2]
    expect(payload.structure_meta).toEqual({
      source_workflow_id: "wf-1",
      needs_review: true,
    })
    expect(toast).toHaveBeenCalledWith("Scene 已标记为需复核", "success")
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

  it("requires primary scene selection before previewing AI fusion draft", async () => {
    api.outline.previewSceneFusion.mockResolvedValue({
      mode: "fusion",
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      draft_scene: {
        title: "潜入与撤离",
        goal: "取得密信并撤离",
        core_conflict: "守卫与追兵前后夹击",
        emotional_beat: "紧张升级",
        must_happen: "带出密信",
        must_not_happen: "暴露盟友",
        chapter_ids: ["1", "2", "3"],
      },
      field_references: {
        goal: [
          { scene_id: "s1", title: "潜入", value: "潜入王宫", role: "primary" },
          { scene_id: "s2", title: "撤离", value: "带着密信撤离", role: "source" },
        ],
      },
      conflicts: [],
      warnings: ["章节跨度较大"],
    })
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1", "s2"])

    await sceneWorkbenchView._startManualFusion()
    expect(showModal.mock.calls[0][0]).toBe("选择主 Scene")
    document.body.innerHTML = showModal.mock.calls[0][1]
    await showModal.mock.calls[0][2][1].handler()

    expect(api.outline.previewSceneFusion).toHaveBeenCalledWith("p1", {
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
    })
    expect(showModal).toHaveBeenCalled()
    const [title, body, buttons] = showModal.mock.calls[1]
    expect(title).toBe("Scene AI 草稿审稿")
    expect(body).toContain("潜入与撤离")
    expect(body).toContain("取得密信并撤离")
    expect(body).toContain("章节跨度较大")
    expect(body).toContain("主 Scene 原值")
    expect(body).toContain("潜入王宫")
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
    const preview = {
      mode: "fusion",
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      draft_scene: { title: "融合草稿", chapter_ids: ["1", "2", "3"] },
      field_references: {},
      warnings: [],
    }
    api.outline.saveSceneFusion.mockResolvedValue({ status: mode === "discard" ? "discarded" : "saved" })
    sceneWorkbenchView._workbench = workbenchPayload

    sceneWorkbenchView._showFusionPreview(preview, ["s1", "s2"])
    const buttons = showModal.mock.calls[0][2]
    await buttons.find((button) => button.text === buttonText).handler()

    const expectedPayload = {
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      mode,
    }
    if (mode !== "discard") {
      expectedPayload.fused_scene = {
        title: "融合草稿",
        goal: null,
        core_conflict: null,
        emotional_beat: null,
        must_happen: null,
        must_not_happen: null,
        chapter_ids: ["1", "2", "3"],
        structure_meta: {
          draft_review_mode: "fusion",
          primary_scene_id: "s1",
          confidence: null,
          draft_review_warnings: [],
          draft_review_conflicts: [],
        },
      }
    }
    expect(api.outline.saveSceneFusion).toHaveBeenCalledWith("p1", expectedPayload)
    expect(closeModal).toHaveBeenCalled()
    expect(router.refresh).toHaveBeenCalled()
  })

  it("saves edited manual fusion fields with edit_then_save and refreshes", async () => {
    const preview = {
      mode: "fusion",
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      draft_scene: {
        title: "融合草稿",
        goal: "旧目标",
        core_conflict: "旧冲突",
        emotional_beat: "旧情绪",
        must_happen: "旧必须",
        must_not_happen: "旧禁止",
        chapter_ids: ["1", "2"],
      },
      field_references: {},
      warnings: [],
    }
    api.outline.saveSceneFusion.mockResolvedValue({ status: "saved" })
    sceneWorkbenchView._workbench = workbenchPayload

    sceneWorkbenchView._showFusionPreview(preview, ["s1", "s2"])
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
      primary_scene_id: "s1",
      mode: "edit_then_save",
      fused_scene: {
        title: "用户改标题",
        goal: "用户改目标",
        core_conflict: "用户改冲突",
        emotional_beat: "用户改情绪",
        must_happen: "用户改必须",
        must_not_happen: "用户改禁止",
        chapter_ids: ["5", "6"],
        structure_meta: {
          draft_review_mode: "fusion",
          primary_scene_id: "s1",
          confidence: null,
          draft_review_warnings: [],
          draft_review_conflicts: [],
        },
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

  it("starts selected mechanical merge separately from AI fusion draft", async () => {
    api.outline.previewSceneMerge.mockResolvedValue({
      operation: "merge",
      chapter_mapping_change: { after: { s1: ["1", "2"] } },
      field_changes: {},
      warnings: [],
    })
    api.outline.mergeScenes.mockResolvedValue({ scene: { id: "s1" } })
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1", "s2"])

    await sceneWorkbenchView._startSelectedMerge()
    expect(showModal.mock.calls[0][0]).toBe("选择目标 Scene")
    document.body.innerHTML = showModal.mock.calls[0][1]
    await showModal.mock.calls[0][2][1].handler()

    expect(api.outline.previewSceneMerge).toHaveBeenCalledWith("p1", {
      target_scene_id: "s1",
      source_scene_ids: ["s2"],
    })
    expect(api.outline.previewSceneFusion).not.toHaveBeenCalled()
  })

  it("uses unified draft review for split preview and submits edited drafts", async () => {
    api.outline.previewSceneSplit.mockResolvedValue({
      operation: "split",
      chapter_mapping_change: { after: { s1: ["1"] } },
      field_changes: {},
      warnings: ["拆分不会修改正文内容。"],
      draft_scenes: [
        { title: "前半", goal: "前半目标", chapter_ids: ["1"] },
        { title: "后半", goal: "后半目标", chapter_ids: ["2"] },
      ],
      field_references: {
        title: [{ scene_id: "s1", title: "潜入", value: "潜入", role: "primary" }],
      },
    })
    api.outline.splitScene.mockResolvedValue({ scene: { id: "s1" } })
    sceneWorkbenchView._workbench = workbenchPayload

    await sceneWorkbenchView._previewAndSplit("s1", 2)
    const [title, body, buttons] = showModal.mock.calls[0]
    expect(title).toBe("Scene AI 草稿审稿")
    expect(body).toContain("AI 拆分草稿")
    expect(body).toContain("scene-split-0-title")
    document.body.innerHTML = body
    document.getElementById("scene-split-0-title").value = "用户前半"
    document.getElementById("scene-split-1-title").value = "用户后半"

    await buttons[1].handler()

    expect(api.outline.splitScene).toHaveBeenCalledWith("p1", {
      source_scene_id: "s1",
      split_chapter_index: 2,
      draft_scenes: [
        { title: "用户前半", goal: "前半目标" },
        { title: "用户后半", goal: "后半目标" },
      ],
      confirmed: true,
    })
  })

  it("opens cross-chapter suggestions through draft review instead of saving", async () => {
    showModal.mockReset()
    showModal.mockImplementation(() => {})
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._crossChapterProgress = {
      taskId: "task-1",
      done: true,
      raw: {
        result: {
          suggestions: [
            {
              source_scene_ids: ["s1", "s2"],
              chapter_span: [1, 3],
              confidence: 0.8,
              stop_reason: "keep_separate",
              reason: "同一场追击",
              proposed_scene: { title: "跨章追击" },
              scan_trace: [],
            },
          ],
        },
      },
    }

    sceneWorkbenchView._showCrossChapterSuggestions()
    const buttons = showModal.mock.calls[0][2]
    await buttons[0].handler()

    expect(api.outline.saveSceneFusion).not.toHaveBeenCalled()
    expect(showModal.mock.calls[1][0]).toBe("选择主 Scene")
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
