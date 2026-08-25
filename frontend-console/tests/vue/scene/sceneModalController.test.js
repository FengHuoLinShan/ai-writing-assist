import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const confirmAsync = vi.hoisted(() => vi.fn())
vi.mock("../../../shared/confirmAsync.js", () => ({ confirmAsync }))
const referencePicker = vi.hoisted(() => {
  const harness = { refs: [], configs: [], pickers: [] }
  harness.create = vi.fn((config) => {
    const picker = {
      destroy: vi.fn(),
      getRefs: vi.fn(() => harness.refs),
    }
    harness.configs.push(config)
    harness.pickers.push(picker)
    return picker
  })
  return harness
})
vi.mock("../../../shared/referencePicker.js", () => ({ createReferencePicker: referencePicker.create }))

import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { createSceneModalController } from "../../../vue/views/scene/sceneModalController.js"

const items = [
  { scene: { id: "s1", title: "潜入", chapter_ids: ["1", "2"], status: "draft" } },
  { scene: { id: "s2", title: "撤离", chapter_ids: ["3"], status: "draft" } },
]

describe("scene modal workflows", () => {
  let api
  let state
  let toast
  let closeModal
  let refresh
  let clearSelection
  let latestButtons
  let controller
  let fusionPreviewResult

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    document.body.innerHTML = '<div id="modal-body"></div><div id="modal-footer"></div>'
    state = { currentProjectId: "p1", currentView: "outline", currentSubView: "scenes" }
    toast = vi.fn()
    closeModal = vi.fn()
    refresh = vi.fn(async () => {})
    clearSelection = vi.fn()
    fusionPreviewResult = null
    latestButtons = []
    referencePicker.refs = []
    referencePicker.configs.length = 0
    referencePicker.pickers.length = 0
    referencePicker.create.mockClear()
    api = {
      outline: {
        getSceneWorkbench: vi.fn(),
        previewSceneMerge: vi.fn(),
        mergeScenes: vi.fn(),
        previewSceneFusionTask: vi.fn((_projectId, data) => Promise.resolve({ task_id: data.operation_id, status: "pending" })),
        saveSceneFusion: vi.fn(),
        previewSceneSplit: vi.fn(),
        splitScene: vi.fn(),
        updateSceneWorkbenchMapping: vi.fn(),
        applySceneReplacement: vi.fn(),
        dismissFusionSuggestions: vi.fn(),
        reviewSceneSourceMappings: vi.fn(),
      },
      tasks: {
        get: vi.fn((taskId) => Promise.resolve({ id: taskId, task_type: "scene_fusion_preview", status: "done", result: fusionPreviewResult })),
        cancel: vi.fn(),
      },
    }
    setBridgeOverrides({
      api,
      state,
      toast,
      closeModal,
      esc: (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;"),
      showModalHtml: vi.fn((_title, body, buttons) => {
        document.getElementById("modal-body").innerHTML = body
        latestButtons = buttons
      }),
    })
    confirmAsync.mockReset().mockResolvedValue(true)
    controller = createSceneModalController({
      projectId: "p1",
      getItems: () => items,
      getSuggestions: () => [],
      refresh,
      clearSelection,
    })
  })

  afterEach(() => {
    controller?.dispose()
    resetBridgeOverrides()
  })

  const action = (text) => latestButtons.find((button) => button.text === text)?.handler

  it("does not recover another tab's scene fusion receipt", () => {
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
      id: "p1:scene_fusion_preview:other-tab-task",
      taskId: "other-tab-task",
      workflowType: "scene_fusion_preview",
      projectId: "p1",
      view: "outline",
      meta: { sourceSceneIds: ["s1", "s2"] },
    }]))

    expect(controller.recoverFusionTask()).toBe(false)
    expect(api.tasks.get).not.toHaveBeenCalled()
  })

  it("previews and confirms a mechanical merge with the selected target", async () => {
    api.outline.previewSceneMerge.mockResolvedValue({
      operation: "merge",
      chapter_mapping_change: {
        before: { s1: ["1", "2"], s2: ["3"] },
        after: { s1: ["1", "2", "3"], s2: [] },
      },
      field_changes: { goal: { before: null, after: "取得密信" } },
      related_threads: { count: 1 },
      related_foreshadowing: { count: 2 },
      related_reveals: { count: 0 },
      warnings: ["关联资产仅提示，不会自动阻断合并。"],
    })
    api.outline.mergeScenes.mockResolvedValue({ status: "merged" })

    expect(controller.startSelectedMerge(["s1", "s2"])).toBe(true)
    await action("预览合并影响")()
    expect(api.outline.previewSceneMerge).toHaveBeenCalledWith("p1", {
      target_scene_id: "s1",
      source_scene_ids: ["s2"],
    })
    const previewText = document.getElementById("modal-body").textContent
    expect(previewText).toContain("保留「潜入」")
    expect(previewText).toContain("撤离")
    expect(previewText).toContain("第 1 章 / 第 2 章 → 第 1 章 / 第 2 章 / 第 3 章")
    expect(previewText).toContain("取得密信")
    expect(previewText).not.toContain("s1")
    expect(previewText).not.toContain("s2")
    expect(previewText).not.toContain("merge")
    expect(document.querySelector("#modal-body pre")).toBeNull()

    await action("确认合并")()
    expect(api.outline.mergeScenes).toHaveBeenCalledWith("p1", {
      target_scene_id: "s1",
      source_scene_ids: ["s2"],
      confirmed: true,
    })
    expect(clearSelection).toHaveBeenCalledOnce()
    expect(refresh).toHaveBeenCalledOnce()
  })

  it("edits and saves an AI fusion while preserving the original scenes", async () => {
    fusionPreviewResult = {
      primary_scene_id: "s1",
      draft_scene: {
        title: "旧融合标题", goal: "离开", core_conflict: "追兵", narrative_tag: "draft",
        chapter_ids: ["1", "2", "3"], structure_meta: { source: "ai" },
      },
      field_references: {}, warnings: ["需复核"], conflicts: [], confidence: 0.8,
    }
    api.outline.saveSceneFusion.mockResolvedValue({ status: "saved" })

    controller.startFusion(["s1", "s2"])
    await action("生成 AI 融合建议")()
    await vi.waitFor(() => expect(api.tasks.get).toHaveBeenCalled())
    expect(controller.showCompletedFusionPreview()).toBe(true)
    document.getElementById("scene-fusion-title").value = "作者修订标题"
    await action("继续编辑融合结果后再保存")()

    expect(api.outline.saveSceneFusion).toHaveBeenCalledWith("p1", expect.objectContaining({
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      mode: "keep_originals",
      fused_scene: expect.objectContaining({
        title: "作者修订标题",
        chapter_ids: ["1", "2", "3"],
        structure_meta: expect.objectContaining({ draft_review_mode: "fusion", primary_scene_id: "s1" }),
      }),
    }))
    expect(sessionStorage.getItem("novel_active_workflows_v1")).toBe("[]")
  })

  it("does not start a second fusion preview while the current session is running", async () => {
    let resolveTask
    api.tasks.get.mockImplementation(() => new Promise((resolve) => { resolveTask = resolve }))

    controller.startFusion(["s1", "s2"])
    await action("生成 AI 融合建议")()
    await vi.waitFor(() => expect(api.tasks.get).toHaveBeenCalledOnce())

    controller.startFusion(["s1", "s2"])
    await action("生成 AI 融合建议")()
    expect(api.outline.previewSceneFusionTask).toHaveBeenCalledOnce()
    expect(toast).toHaveBeenCalledWith("已有场景融合预览正在生成", "info")

    resolveTask({ id: "late", task_type: "scene_fusion_preview", status: "cancelled" })
  })

  it("discards an AI fusion without sending a generated scene payload", async () => {
    fusionPreviewResult = {
      draft_scene: { title: "候选", narrative_tag: "draft", chapter_ids: ["1", "3"] },
      field_references: {},
    }
    api.outline.saveSceneFusion.mockResolvedValue({ status: "discarded" })

    controller.startFusion(["s1", "s2"], "suggestion-1")
    await action("生成 AI 融合建议")()
    await vi.waitFor(() => expect(api.tasks.get).toHaveBeenCalled())
    expect(controller.showCompletedFusionPreview()).toBe(true)
    await action("放弃融合结果")()

    expect(api.outline.saveSceneFusion).toHaveBeenCalledWith("p1", {
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      mode: "discard",
      suggestion_id: "suggestion-1",
    })
  })

  it("previews a chapter split and saves the edited drafts", async () => {
    api.outline.previewSceneSplit.mockResolvedValue({
      draft_scenes: [
        { title: "前半段", narrative_tag: "draft", chapter_ids: ["1"] },
        { title: "后半段", narrative_tag: "turning_point", chapter_ids: ["2"] },
      ],
      field_references: {}, chapter_mapping_change: { after: { s1: ["1"], new: ["2"] } },
    })
    api.outline.splitScene.mockResolvedValue({ status: "split" })

    expect(controller.startSplit("s1")).toBe(true)
    await action("生成拆分预览")()
    const previewText = document.getElementById("modal-body").textContent
    expect(previewText).toContain("保留原场景")
    expect(previewText).toContain("前半段")
    expect(previewText).toContain("第 1 章")
    expect(previewText).toContain("创建新场景")
    expect(previewText).toContain("后半段")
    expect(previewText).toContain("第 2 章")
    expect(previewText).not.toContain("s1")
    expect(document.querySelector("#modal-body pre")).toBeNull()
    document.getElementById("scene-split-1-title").value = "作者修订后半段"
    await action("确认拆分")()

    expect(api.outline.splitScene).toHaveBeenCalledWith("p1", expect.objectContaining({
      source_scene_id: "s1",
      split_chapter_index: 2,
      confirmed: true,
      draft_scenes: expect.arrayContaining([
        expect.objectContaining({ title: "前半段" }),
        expect.objectContaining({ title: "作者修订后半段" }),
      ]),
    }))
  })

  it("applies an edited replacement only after explicit confirmation", async () => {
    const suggestion = {
      id: "replacement-1",
      suggestion_kind: "replacement",
      source_scene_ids: ["s1"],
      proposed_scene: {
        draft_scenes: [{ title: "AI 候选", goal: "逃离", chapter_ids: ["1"] }],
      },
    }
    api.outline.applySceneReplacement.mockResolvedValue({ downstream_refresh_required: ["地图摘要"] })
    controller = createSceneModalController({
      projectId: "p1",
      getItems: () => items,
      getSuggestions: () => [suggestion],
      refresh,
      clearSelection,
    })

    controller.showSuggestions("replacement-1")
    document.querySelector('[data-replacement-field="title"]').value = "作者编辑候选"
    await action("编辑后采用，原场景移入历史")()

    expect(confirmAsync).toHaveBeenCalledOnce()
    expect(api.outline.applySceneReplacement).toHaveBeenCalledWith("p1", expect.objectContaining({
      suggestion_id: "replacement-1",
      decision: "edit_then_replace",
      confirmed: true,
      draft_scenes: [expect.objectContaining({ title: "作者编辑候选" })],
    }))
  })

  it("assigns an unowned chapter and edits the full chapter mapping", async () => {
    api.outline.updateSceneWorkbenchMapping.mockResolvedValue({})

    controller.assignChapter(3)
    await action("确认分配")()
    expect(api.outline.updateSceneWorkbenchMapping).toHaveBeenNthCalledWith(1, "p1", "s1", {
      chapter_ids: ["1", "2", "3"],
    })

    controller.showAssignChapters("s2", ["4"])
    document.querySelector('input[name="scene-assign-chapter"][value="4"]').checked = true
    await action("保存章节映射")()
    expect(api.outline.updateSceneWorkbenchMapping).toHaveBeenNthCalledWith(2, "p1", "s2", {
      chapter_ids: ["3", "4"],
    })
  })

  it("drops a late merge preview after disposal", async () => {
    let resolvePreview
    api.outline.previewSceneMerge.mockImplementation(() => new Promise((resolve) => { resolvePreview = resolve }))

    controller.startSelectedMerge(["s1", "s2"])
    const pending = action("预览合并影响")()
    controller.dispose()
    resolvePreview({ operation: "merge" })
    await pending

    expect(action("确认合并")).toBeUndefined()
    expect(api.outline.mergeScenes).not.toHaveBeenCalled()
  })

  it("requires the destructive fusion confirmation before deprecating originals", async () => {
    fusionPreviewResult = {
      draft_scene: { title: "融合候选", narrative_tag: "draft", chapter_ids: ["1", "2", "3"] },
      field_references: {},
    }
    api.outline.saveSceneFusion.mockResolvedValue({ status: "saved" })
    controller.startFusion(["s1", "s2"])
    await action("生成 AI 融合建议")()
    await vi.waitFor(() => expect(api.tasks.get).toHaveBeenCalled())
    expect(controller.showCompletedFusionPreview()).toBe(true)

    expect(document.querySelector('[data-role="fusion-deprecation-confirm"]').hidden).toBe(true)
    expect(action("将 2 个原场景移入历史并保存")()).toBe(false)
    expect(api.outline.saveSceneFusion).not.toHaveBeenCalled()
    expect(document.querySelector('[data-role="fusion-deprecation-confirm"]').hidden).toBe(false)

    document.querySelector('[data-action="confirm-fusion-deprecation"]').click()
    await vi.waitFor(() => expect(api.outline.saveSceneFusion).toHaveBeenCalledWith("p1", expect.objectContaining({
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      mode: "deprecate_originals",
      fused_scene: expect.objectContaining({ title: "融合候选" }),
    })))
  })

  it("merges a single Scene selected by the searchable reference picker", async () => {
    api.outline.getSceneWorkbench.mockResolvedValue({ items: [
      { scene: items[0].scene },
      { scene: items[1].scene },
      { scene: { id: "history", title: "历史 Scene", status: "deprecated", chapter_ids: ["4"] } },
    ] })
    api.outline.previewSceneMerge.mockResolvedValue({ operation: "merge" })
    api.outline.mergeScenes.mockResolvedValue({ status: "merged" })

    expect(controller.startMerge("s1")).toBe(true)
    const source = referencePicker.configs[0].sources[0]
    const results = await source.search("撤", { projectId: "p1", limit: 10 })
    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", null, {
      q: "撤", view_mode: "normal", skip: 0, limit: 10,
    })
    expect(results.map((item) => item.id)).toEqual(["s2"])

    referencePicker.refs = [{ kind: "scene", id: "s2" }]
    await action("预览合并影响")()
    expect(referencePicker.pickers[0].destroy).toHaveBeenCalledOnce()
    expect(api.outline.previewSceneMerge).toHaveBeenCalledWith("p1", {
      target_scene_id: "s1", source_scene_ids: ["s2"],
    })
    await action("确认合并")()
    expect(api.outline.mergeScenes).toHaveBeenCalledWith("p1", {
      target_scene_id: "s1", source_scene_ids: ["s2"], confirmed: true,
    })
  })

  it("confirms chapter-only source mapping with the expected fingerprint", async () => {
    api.outline.reviewSceneSourceMappings.mockResolvedValue({ status: "reviewed" })

    expect(controller.confirmSourceMapping("s1", "fingerprint-1")).toBe(true)
    await action("确认仅按章节关联")()

    expect(api.outline.reviewSceneSourceMappings).toHaveBeenCalledWith("p1", {
      items: [{ scene_id: "s1", expected_fingerprint: "fingerprint-1" }],
      decision: "accept_chapter_only",
      confirmed: true,
    })
    expect(refresh).toHaveBeenCalledOnce()
  })

  it("bulk-dismisses fusion suggestions but preserves replacement reviews", async () => {
    const suggestions = [
      { id: "fusion-1", suggestion_kind: "fusion", proposed_action: "merge" },
      { id: "separate-1", suggestion_kind: "fusion", proposed_action: "keep_separate" },
      { id: "replacement-1", suggestion_kind: "replacement" },
    ]
    controller.dispose()
    controller = createSceneModalController({
      projectId: "p1",
      getItems: () => items,
      getSuggestions: () => suggestions,
      refresh,
      clearSelection,
    })
    api.outline.dismissFusionSuggestions.mockResolvedValue({ status: "dismissed" })

    expect(controller.dismissAllSuggestions()).toBe(true)
    expect(document.getElementById("modal-body").textContent).toContain("需要单独检查的场景替换建议不会被忽略")
    await action("确认忽略 2 条")()

    expect(api.outline.dismissFusionSuggestions).toHaveBeenCalledWith("p1", {
      suggestion_ids: ["fusion-1", "separate-1"],
      confirmed: true,
    })
  })
})
