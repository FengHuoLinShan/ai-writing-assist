import { beforeEach, describe, expect, it, vi } from "vitest"

import sceneWorkbenchView from "../views/sceneWorkbenchView.js"
import {
  persistActiveWorkflow,
  recoverActiveWorkflows,
} from "../shared/workflowProgress.js"
import {
  autoConfirm,
  captureModalHandler,
  clearDocument,
  modalHtmlFromCall,
  resetState,
} from "./helpers.js"

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
  resetState({ currentProjectId: "p1", currentView: "scene", currentSubView: "s1" })
  clearDocument()
  localStorage.clear()
  vi.clearAllMocks()
  api.outline.getSceneWorkbench = vi.fn().mockResolvedValue(workbenchPayload)
  api.outline.updateSceneWorkbenchMapping = vi.fn()
  api.outline.reviewSceneWorkbench = vi.fn().mockResolvedValue({ items: [] })
  api.outline.reviewSceneSourceMappings = vi.fn().mockResolvedValue({ items: [] })
  api.outline.previewSceneFusion = vi.fn()
  api.outline.saveSceneFusion = vi.fn()
  api.outline.previewSceneMerge = vi.fn()
  api.outline.mergeScenes = vi.fn()
  api.outline.previewSceneSplit = vi.fn()
  api.outline.splitScene = vi.fn()
  api.outline.listFusionSuggestions = vi.fn().mockResolvedValue({ items: [], total: 0 })
  api.outline.dismissFusionSuggestions = vi.fn().mockResolvedValue({ dismissed: 0 })
  api.outline.updateScene.mockResolvedValue({ id: "s1" })
  sceneWorkbenchView._loading = false
  sceneWorkbenchView._fusionPreviewPending = false
  sceneWorkbenchView._fusionPreviewProjectId = null
  sceneWorkbenchView._fusionPreviewRequestSeq = 0
  sceneWorkbenchView._activeDraftReview = null
  sceneWorkbenchView._workbench = null
  sceneWorkbenchView._total = 0
  sceneWorkbenchView._activeHealth = null
  sceneWorkbenchView._filters = {
    health: "",
    q: "",
    status: "",
    source: "",
    workflow_id: "",
    needs_review: "",
    boundary_status: "",
    phase: "",
    phase1a_fallback: false,
    chapter_from: "",
    chapter_to: "",
    confidence_band: "",
    skip: 0,
    limit: 20,
  }
  sceneWorkbenchView._advancedFiltersOpen = false
  sceneWorkbenchView._selectedFusionSceneIds = new Set()
  sceneWorkbenchView._autoExtractTaskId = null
  sceneWorkbenchView._autoExtractProgress = null
  sceneWorkbenchView._autoExtractPoller = null
  sceneWorkbenchView._autoExtractMeta = null
  sceneWorkbenchView._autoExtractCancelPending = false
  sceneWorkbenchView._fusionSuggestions = []
  sceneWorkbenchView._mobileDetailOpen = false
  sceneWorkbenchView._selectedSceneIdValue = null
})

describe("sceneWorkbenchView", () => {
  it("renders scene auto extraction action", async () => {
    sceneWorkbenchView._workbench = workbenchPayload

    const html = await sceneWorkbenchView.render()

    expect(html).toContain("场景（scene）自动提取")
    expect(html).toContain("scene-workbench-shell")
    expect(html).toContain("scene-workbench-actions")
    expect(html).toContain('data-action="scene-auto-extract"')
    expect(html).toContain("再选 2 个即可融合")
    expect(html).toContain('data-action="toggle-visible-fusion-selection"')
    expect(html).toContain('aria-label="选择用于批量操作"')
    expect(html).not.toContain("<span>融合</span>")
    expect(html).not.toContain('data-action="clear-fusion-selection"')
    expect(html).not.toContain(">清空</button>")
    expect(html).toContain('data-action="start-selected-merge"')
    expect(html).toContain('data-action="handle-selected-context-actions"')
    expect(html).toContain("批量处理")
    expect(html.indexOf("批量处理")).toBeLessThan(html.indexOf("机械合并"))
    expect(html).toContain("机械合并")
    expect(html).toContain('data-action="start-ai-fusion-draft"')
    expect(html).toContain("AI 融合建议")
    expect(html).toContain("打开写作")
    expect(html).toContain("合并")
    expect(html).toContain("拆分")
  })

  it("selects visible scenes for manual fusion", () => {
    sceneWorkbenchView._workbench = workbenchPayload

    sceneWorkbenchView._selectVisibleFusionScenes()

    expect(sceneWorkbenchView._selectedFusionSceneIds).toEqual(new Set(["s1", "s2"]))
    expect(router.renderCurrentView).not.toHaveBeenCalled()
  })

  it("toggles current list fusion selection between select all and deselect all", () => {
    sceneWorkbenchView._workbench = workbenchPayload

    sceneWorkbenchView._toggleVisibleFusionSelection()

    expect(sceneWorkbenchView._selectedFusionSceneIds).toEqual(new Set(["s1", "s2"]))

    sceneWorkbenchView._toggleVisibleFusionSelection()

    expect(sceneWorkbenchView._selectedFusionSceneIds.size).toBe(0)
    expect(router.renderCurrentView).not.toHaveBeenCalled()
  })

  it("renders current list selection toggle as cancel when all visible scenes are selected", async () => {
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1", "s2"])

    const html = await sceneWorkbenchView.render()

    expect(html).toContain("取消全选")
    expect(html).not.toContain(">清空</button>")
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

  it("selects another scene without rerendering or resetting list scroll", async () => {
    state.currentView = "scene"
    sceneWorkbenchView._workbench = workbenchPayload
    window.history.replaceState({ view: "scene", subView: "s1", projectId: "p1" }, "", "#workbench/p1/scene/s1")
    document.body.innerHTML = `<main id="workspace-content">${await sceneWorkbenchView.render()}</main>`
    sceneWorkbenchView._bindEvents()
    const organize = document.querySelector(".scene-workbench__organize")
    organize.scrollTop = 96
    vi.clearAllMocks()

    document.querySelector('.scene-workbench-row[data-id="s2"] [data-action="select-workbench-scene"]').click()

    expect(state.currentSubView).toBe("s2")
    expect(window.location.hash).toBe("#workbench/p1/scene/s2")
    expect(organize.scrollTop).toBe(96)
    expect(document.querySelector('.scene-workbench-row[data-id="s1"]').classList.contains("is-selected")).toBe(false)
    expect(document.querySelector('.scene-workbench-row[data-id="s2"]').classList.contains("is-selected")).toBe(true)
    expect(document.querySelector(".scene-workbench__detail").textContent).toContain("撤离")
    expect(router.navigate).not.toHaveBeenCalled()
    expect(router.renderCurrentView).not.toHaveBeenCalled()
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("keeps the outline scenes tab active when selecting an embedded scene", () => {
    state.currentView = "outline"
    state.currentSubView = "scenes"
    sceneWorkbenchView._workbench = workbenchPayload
    window.history.replaceState(
      { view: "outline", subView: "scenes", projectId: "p1" },
      "",
      "#workbench/p1/outline/scenes",
    )

    sceneWorkbenchView._selectSceneInPlace("s2")

    expect(state.currentView).toBe("outline")
    expect(state.currentSubView).toBe("scenes")
    expect(sceneWorkbenchView._selectedSceneId()).toBe("s2")
    expect(window.location.hash).toBe("#workbench/p1/outline/scenes?scene_id=s2")
  })

  it("restores the embedded scene selection from browser history", () => {
    state.currentView = "outline"
    state.currentSubView = "scenes"
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._selectedSceneIdValue = "s2"

    window.history.replaceState(
      { view: "outline", subView: "scenes", projectId: "p1" },
      "",
      "#workbench/p1/outline/scenes?scene_id=s1",
    )

    expect(sceneWorkbenchView._selectedSceneId()).toBe("s1")

    window.history.replaceState(
      { view: "outline", subView: "scenes", projectId: "p1" },
      "",
      "#workbench/p1/outline/scenes?scene_id=s2",
    )

    expect(sceneWorkbenchView._selectedSceneId()).toBe("s2")

    window.history.replaceState(
      { view: "outline", subView: "scenes", projectId: "p1" },
      "",
      "#workbench/p1/outline/scenes",
    )

    expect(sceneWorkbenchView._selectedSceneId()).toBe("s1")
  })

  it("submits scene auto extraction stage task", async () => {
    api.imports.startStage.mockResolvedValue({ task_id: "scene-task" })
    sceneWorkbenchView._showSceneAutoExtractForm()
    expect(showModal.mock.calls[0][1].html).toContain("最大推理 + Phase 1c 融合")
    expect(showModal.mock.calls[0][1].html).toContain("自动采用通过门禁")
    expect(showModal.mock.calls[0][1].html).toContain("进入待处理")
    expect(showModal.mock.calls[0][2][0].text).toBe("确认并开始提取")
    document.body.innerHTML += `
      <input id="scene-auto-extract-start" value="1" />
      <input id="scene-auto-extract-end" value="5" />
      <input id="scene-auto-extract-high-quality" type="checkbox" />
    `

    await captureModalHandler()()

    expect(api.imports.startStage).toHaveBeenCalledWith(
      "scenes",
      "p1",
      1,
      5,
      false,
      false,
      {
        adoption_policy: "user_authorized_pipeline",
        authorization_confirmed: true,
      },
    )
    expect(toast).toHaveBeenCalledWith(
      "场景（scene）自动提取任务已提交：scene-task",
      "success",
    )
  })

  it("passes high quality flag for scene auto extraction", async () => {
    api.imports.startStage.mockResolvedValue({ task_id: "scene-task" })
    sceneWorkbenchView._showSceneAutoExtractForm()
    document.body.innerHTML += `
      <input id="scene-auto-extract-start" value="1" />
      <input id="scene-auto-extract-end" value="5" />
      <input id="scene-auto-extract-high-quality" type="checkbox" checked />
    `

    await captureModalHandler()()

    expect(api.imports.startStage).toHaveBeenCalledWith(
      "scenes",
      "p1",
      1,
      5,
      false,
      true,
      {
        adoption_policy: "user_authorized_pipeline",
        authorization_confirmed: true,
      },
    )
  })

  it("confirms overwrite before forcing scene auto extraction", async () => {
    api.imports.startStage
      .mockResolvedValueOnce({ requires_confirmation: true, warning: "已有 Scene 会被覆盖" })
      .mockResolvedValueOnce({ task_id: "scene-task" })
    autoConfirm()
    sceneWorkbenchView._showSceneAutoExtractForm()
    document.body.innerHTML += `
      <input id="scene-auto-extract-start" value="107" />
      <input id="scene-auto-extract-end" value="160" />
      <input id="scene-auto-extract-high-quality" type="checkbox" />
    `

    await captureModalHandler()()

    expect(confirmAction).toHaveBeenCalledWith(
      "已有 Scene 会被覆盖",
      expect.any(Function),
      "确认覆盖",
    )
    expect(api.imports.startStage).toHaveBeenNthCalledWith(
      1,
      "scenes",
      "p1",
      107,
      160,
      false,
      false,
      {
        adoption_policy: "user_authorized_pipeline",
        authorization_confirmed: true,
      },
    )
    expect(api.imports.startStage).toHaveBeenNthCalledWith(
      2,
      "scenes",
      "p1",
      107,
      160,
      true,
      false,
      {
        adoption_policy: "user_authorized_pipeline",
        authorization_confirmed: true,
      },
    )
    expect(toast).toHaveBeenCalledWith(
      "场景（scene）自动提取任务已提交：scene-task",
      "success",
    )
  })

  it("does not start polling when scene auto extraction returns no task id", async () => {
    api.imports.startStage.mockResolvedValue({ message: "章节范围为空" })
    const pollingSpy = vi.spyOn(sceneWorkbenchView, "_startAutoExtractPolling")
    sceneWorkbenchView._showSceneAutoExtractForm()
    document.body.innerHTML += `
      <input id="scene-auto-extract-start" value="107" />
      <input id="scene-auto-extract-end" value="160" />
      <input id="scene-auto-extract-high-quality" type="checkbox" />
    `

    await captureModalHandler()()

    expect(pollingSpy).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("章节范围为空", "warning")
    expect(toast).not.toHaveBeenCalledWith("taskId is required", "error")
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

  it("recovers a persisted scene extraction task with its project id", async () => {
    api.tasks.get.mockResolvedValue({
      task_id: "scene-recover",
      task_type: "scene_auto_extraction",
      status: "running",
      progress: 0.2,
      result: { phase: "running" },
    })
    persistActiveWorkflow({
      taskId: "scene-recover",
      workflowType: "scene_auto_extraction",
      projectId: "p1",
      view: "scene",
      meta: { start_chapter: 2, end_chapter: 6 },
    })

    await sceneWorkbenchView.onEnter()
    await Promise.resolve()

    expect(api.tasks.get).toHaveBeenCalledWith("scene-recover", "p1")
    expect(sceneWorkbenchView._autoExtractTaskId).toBe("scene-recover")
    expect(sceneWorkbenchView._autoExtractMeta).toEqual({
      start_chapter: 2,
      end_chapter: 6,
    })
    expect(recoverActiveWorkflows("p1")).toHaveLength(1)
    sceneWorkbenchView.onLeave()
  })

  it("updates scene extraction progress without rerendering or moving the list", async () => {
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._autoExtractTaskId = "scene-running"
    sceneWorkbenchView._autoExtractMeta = { start_chapter: 1, end_chapter: 60 }
    document.body.innerHTML = `<main id="workspace-content">${await sceneWorkbenchView.render()}</main>`
    sceneWorkbenchView._bindEvents()
    const organize = document.querySelector(".scene-workbench__organize")
    const search = document.getElementById("scene-filter-q")
    organize.scrollTop = 88
    search.value = "正在浏览"
    api.tasks.get.mockResolvedValue({
      task_id: "scene-running",
      task_type: "scene_auto_extraction",
      status: "running",
      progress: 0.295,
      result: {
        current_phase: "phase1a_scene_slicing",
        current_item: { kind: "window", completed: 2, total: 4 },
        phase_timeline: [
          { phase: "phase0_plan", status: "completed" },
          { phase: "phase1a_scene_slicing", status: "running" },
        ],
      },
    })

    sceneWorkbenchView._startAutoExtractPolling("scene-running")
    await vi.waitFor(() => {
      expect(
        document.querySelector('[data-role="scene-auto-extract-progress"]')?.textContent,
      ).toContain("Phase 1a · Scene 边界切分｜窗口 2/4")
    })
    sceneWorkbenchView._stopAutoExtractPolling()

    expect(router.renderCurrentView).not.toHaveBeenCalled()
    expect(document.querySelector(".scene-workbench__organize")).toBe(organize)
    expect(organize.scrollTop).toBe(88)
    expect(document.getElementById("scene-filter-q").value).toBe("正在浏览")
    expect(
      document.querySelector('.scene-workbench-row[data-id="s1"]')?.classList.contains("is-selected"),
    ).toBe(true)
  })

  it("retains a failed scene extraction task until dismissed", async () => {
    sceneWorkbenchView._autoExtractTaskId = "scene-failed"
    sceneWorkbenchView._autoExtractProgress = {
      failed: true,
      cancelled: false,
      label: "场景（scene）自动提取",
      statusLabel: "失败",
      message: "API Key 未配置",
      warnings: [],
      phaseArtifacts: {},
      acceptanceChecks: [],
      phaseTimeline: [],
      progressEvents: [],
      phaseErrors: [],
      diagnosticCounts: {},
      assetSummary: {},
    }
    persistActiveWorkflow({
      taskId: "scene-failed",
      workflowType: "scene_auto_extraction",
      projectId: "p1",
      view: "scene",
    })

    expect(sceneWorkbenchView._renderAutoExtractProgress()).toContain(
      'data-action="dismiss-scene-auto-extract"',
    )
    sceneWorkbenchView._dismissAutoExtractProgress()

    expect(recoverActiveWorkflows("p1")).toEqual([])
    expect(sceneWorkbenchView._autoExtractProgress).toBeNull()
  })

  it("confirms and cancels the running scene extraction task for the current project", async () => {
    autoConfirm()
    api.tasks.cancel.mockResolvedValue({
      task_id: "scene-running",
      status: "cancelled",
      cancelled: true,
    })
    sceneWorkbenchView._autoExtractTaskId = "scene-running"
    sceneWorkbenchView._autoExtractMeta = { start_chapter: 2, end_chapter: 6 }
    sceneWorkbenchView._autoExtractProgress = {
      failed: false,
      cancelled: false,
      percent: 20,
      label: "场景（scene）自动提取",
      statusLabel: "进行中",
      message: "正在提取",
      warnings: [],
      phaseArtifacts: {},
      acceptanceChecks: [],
      phaseTimeline: [],
      progressEvents: [],
      phaseErrors: [],
      diagnosticCounts: {},
      assetSummary: {},
    }
    persistActiveWorkflow({
      taskId: "scene-running",
      workflowType: "scene_auto_extraction",
      projectId: "p1",
      view: "scene",
    })

    expect(sceneWorkbenchView._renderAutoExtractProgress()).toContain(
      'data-action="cancel-scene-auto-extract"',
    )
    await sceneWorkbenchView._cancelAutoExtractTask()

    expect(confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("确认取消当前场景自动提取任务"),
      expect.any(Function),
      "确认取消",
    )
    expect(api.tasks.cancel).toHaveBeenCalledWith("scene-running", "p1")
    expect(sceneWorkbenchView._autoExtractProgress.cancelled).toBe(true)
    expect(sceneWorkbenchView._renderAutoExtractProgress()).toContain(
      'data-action="dismiss-scene-auto-extract"',
    )
    expect(recoverActiveWorkflows("p1")).toHaveLength(1)
  })

  it("uses the server window containing a selected scene outside the first page", async () => {
    state.currentView = "outline"
    state.currentSubView = "scenes"
    window.history.replaceState(
      { view: "outline", subView: "scenes", projectId: "p1" },
      "",
      "#workbench/p1/outline/scenes?scene_id=s25",
    )
    api.outline.getSceneWorkbench.mockResolvedValue({
      ...workbenchPayload,
      skip: 20,
      selected_scene_id: "s25",
      items: [{
        ...workbenchPayload.items[0],
        scene: { ...workbenchPayload.items[0].scene, id: "s25", title: "第 25 个 Scene" },
      }],
    })

    await sceneWorkbenchView.onEnter()

    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", "s25", {
      skip: 0,
      limit: 20,
    })
    expect(sceneWorkbenchView._filters.skip).toBe(20)
    expect(sceneWorkbenchView._selectedSceneId()).toBe("s25")
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

  it("clears embedded scene selection before explicit pagination", async () => {
    state.currentView = "outline"
    state.currentSubView = "scenes"
    window.history.replaceState(
      { view: "outline", subView: "scenes", projectId: "p1" },
      "",
      "#workbench/p1/outline/scenes?scene_id=s1",
    )
    sceneWorkbenchView._workbench = { ...workbenchPayload, total: 45 }
    sceneWorkbenchView._total = 45

    await sceneWorkbenchView._changePage(1)

    expect(window.location.hash).toBe("#workbench/p1/outline/scenes")
    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", null, {
      skip: 20,
      limit: 20,
    })
  })

  it("applies management filters through scene workbench API params", async () => {
    api.outline.getSceneWorkbench.mockResolvedValue(workbenchPayload)
    document.body.innerHTML = `
      <input id="scene-filter-q" value="潜入" />
      <input id="scene-filter-chapter-from" value="1" />
      <input id="scene-filter-chapter-to" value="3" />
      <select id="scene-filter-status"><option value="deprecated" selected>废弃</option></select>
      <select id="scene-filter-source"><option value="deep_import" selected>深度导入</option></select>
      <input id="scene-filter-workflow-id" value="wf-17" />
      <select id="scene-filter-needs-review"><option value="true" selected>需复核</option></select>
      <select id="scene-filter-boundary-status"><option value="uncertain" selected>边界不确定</option></select>
      <select id="scene-filter-phase"><option value="phase1a_fallback" selected>Phase 1A fallback</option></select>
      <select id="scene-filter-confidence-band"><option value="low" selected>低于 0.5</option></select>
      <label><input id="scene-filter-phase1a-fallback" type="checkbox" checked /> fallback</label>
    `

    await sceneWorkbenchView._applyManagementFilters()

    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith(
      "p1",
      "s1",
      expect.objectContaining({
        q: "潜入",
        chapter_from: "1",
        chapter_to: "3",
        status: "deprecated",
        source: "deep_import",
        workflow_id: "wf-17",
        needs_review: true,
        boundary_status: "uncertain",
        phase: "phase1a_fallback",
        phase1a_fallback: true,
        confidence_band: "low",
        skip: 0,
        limit: 20,
      }),
    )
    expect(sceneWorkbenchView._filters.status).toBe("deprecated")
  })

  it("renders common and advanced scene filters", async () => {
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._advancedFiltersOpen = true

    const html = await sceneWorkbenchView.render()

    expect(html).toContain("scene-filter-q")
    expect(html).toContain("scene-filter-chapter-from")
    expect(html).toContain("scene-filter-chapter-to")
    expect(html).toContain("scene-filter-workflow-id")
    expect(html).toContain("scene-filter-confidence-band")
    expect(html).toContain("低于 0.5")
  })

  it("loads server-backed health filter and clears selection", async () => {
    api.outline.getSceneWorkbench.mockResolvedValue(workbenchPayload)
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1"])

    await sceneWorkbenchView._toggleHealthFilter("missing_setup")

    expect(sceneWorkbenchView._filters.health).toBe("missing_setup")
    expect(sceneWorkbenchView._filters.skip).toBe(0)
    expect(sceneWorkbenchView._selectedFusionSceneIds.size).toBe(0)
    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", "s1", {
      health: "missing_setup",
      skip: 0,
      limit: 20,
    })
    expect(router.refresh).toHaveBeenCalled()
  })

  it("reset filters clears health and advanced state", async () => {
    api.outline.getSceneWorkbench.mockResolvedValue(workbenchPayload)
    sceneWorkbenchView._filters = {
      ...sceneWorkbenchView._filters,
      health: "unreviewed",
      q: "潜入",
      skip: 20,
    }
    sceneWorkbenchView._activeHealth = "unreviewed"
    sceneWorkbenchView._advancedFiltersOpen = true
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1"])

    await sceneWorkbenchView._resetManagementFilters()

    expect(sceneWorkbenchView._filters.health).toBe("")
    expect(sceneWorkbenchView._filters.q).toBe("")
    expect(sceneWorkbenchView._filters.skip).toBe(0)
    expect(sceneWorkbenchView._activeHealth).toBeNull()
    expect(sceneWorkbenchView._advancedFiltersOpen).toBe(false)
    expect(sceneWorkbenchView._selectedFusionSceneIds.size).toBe(0)
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

  it("renders server-filtered scene list by health key", async () => {
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      items: [
        {
          kind: "scene",
          health: ["needs_organize"],
          chapter_range: "第 3 章",
          scene: { id: "s2", scene_index: 1, title: "整理项", status: "draft" },
        },
      ],
    }
    sceneWorkbenchView._filters.health = "needs_organize"

    const html = await sceneWorkbenchView.render()

    expect(html).toContain('class="scene-health-filter active"')
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

    expect(html).toContain('data-action="context-review-scene"')
    expect(html).toContain("采用")
    expect(html).toContain("来源与注意")
    expect(html).toContain("需要人工检查")
  })

  it("uses source mapping confirmation as the contextual primary action", async () => {
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      items: [{
        ...workbenchPayload.items[1],
        health: ["needs_organize"],
        health_details: {
          needs_organize: [{
            code: "source_mapping_chapter_only",
            label: "正文定位仅精确到章节",
            fingerprint: "a".repeat(64),
          }],
        },
        scene: {
          ...workbenchPayload.items[1].scene,
          status: "canonical",
          structure_meta: { reviewed_at: "2026-07-10T00:00:00Z" },
        },
      }],
    }

    const html = await sceneWorkbenchView.render()

    expect(html).toContain('data-action="context-confirm-source-mapping"')
    expect(html).toContain("确认章节定位")
    expect(html).toContain('data-action="handle-scene-health"')
    expect(html).toContain("scene-secondary-action")
  })

  it("switches a multi-problem scene to its next action after review", () => {
    const item = {
      ...workbenchPayload.items[0],
      health: ["unreviewed", "needs_organize"],
      health_details: {
        needs_organize: [{
          code: "chunk_chapter_mismatch",
          label: "章节与正文分段不一致",
        }],
      },
    }

    expect(sceneWorkbenchView._contextAction(item)).toMatchObject({
      key: "review",
      label: "采用",
    })

    expect(sceneWorkbenchView._contextAction({
      ...item,
      health: ["needs_organize"],
      scene: {
        ...item.scene,
        status: "canonical",
        structure_meta: { reviewed_at: "2026-07-10T00:00:00Z" },
      },
    })).toMatchObject({
      key: "organize",
      label: "整理映射",
    })
  })

  it("confirms source mapping through the dedicated command", async () => {
    const fingerprint = "b".repeat(64)

    sceneWorkbenchView._confirmSourceMapping("s1", fingerprint)
    const call = showModal.mock.calls[0]
    await call[2][1].handler()

    expect(api.outline.reviewSceneSourceMappings).toHaveBeenCalledWith("p1", {
      items: [{ scene_id: "s1", expected_fingerprint: fingerprint }],
      decision: "accept_chapter_only",
      confirmed: true,
    })
  })

  it("runs the matching contextual action when a health chip is clicked", async () => {
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      items: [{
        ...workbenchPayload.items[1],
        health: ["needs_organize"],
        health_details: {
          needs_organize: [{
            code: "source_mapping_chapter_only",
            label: "正文定位仅精确到章节",
            fingerprint: "c".repeat(64),
          }],
        },
        scene: {
          ...workbenchPayload.items[1].scene,
          status: "canonical",
          structure_meta: { reviewed_at: "2026-07-10T00:00:00Z" },
        },
      }],
    }
    document.body.innerHTML = `<main id="workspace-content">${await sceneWorkbenchView.render()}</main>`
    sceneWorkbenchView._bindEvents()
    showModal.mockClear()

    document.querySelector('.scene-health-chip[data-health="needs_organize"]').click()

    expect(showModal).toHaveBeenCalled()
    expect(showModal.mock.calls[0][0]).toBe("确认章节级正文定位")
  })

  it("offers move, merge, and split from mapping organization", () => {
    sceneWorkbenchView._workbench = workbenchPayload

    sceneWorkbenchView._showOrganizeMapping("s1")

    const actions = showModal.mock.calls[0][2]
    expect(actions.map((action) => action.text)).toEqual(["移动章节", "合并", "拆分"])
    actions[0].handler()
    expect(showModal.mock.calls[1][0]).toBe("移动 / 关联章节")
    const html = modalHtmlFromCall(showModal.mock.calls[1])
    expect(html).toContain('value="1" checked')
    expect(html).toContain('value="2" checked')
    expect(html).toContain('value="4"')
  })

  it("uses the concrete review command for a homogeneous batch", async () => {
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1", "s2"])

    await sceneWorkbenchView._handleSelectedContextActions()

    expect(api.outline.reviewSceneWorkbench).toHaveBeenCalledWith("p1", {
      scene_ids: ["s1", "s2"],
      decision: "review",
    })
    expect(showModal).not.toHaveBeenCalled()
  })

  it("groups mixed batch actions instead of clearing all meanings at once", async () => {
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      items: [
        workbenchPayload.items[0],
        {
          ...workbenchPayload.items[1],
          scene: {
            ...workbenchPayload.items[1].scene,
            status: "canonical",
            structure_meta: { reviewed_at: "2026-07-10T00:00:00Z" },
          },
        },
      ],
    }
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1", "s2"])

    await sceneWorkbenchView._handleSelectedContextActions()

    expect(showModal.mock.calls[0][0]).toBe("批量处理")
    const html = modalHtmlFromCall(showModal.mock.calls[0])
    expect(html).toContain("采用 / 检查")
    expect(html).toContain("普通编辑")
    expect(api.outline.reviewSceneWorkbench).not.toHaveBeenCalled()
  })

  it("loads persisted fusion suggestions into a durable queue", async () => {
    api.outline.getSceneWorkbench.mockResolvedValue({
      ...workbenchPayload,
      fusion_suggestions: { pending_count: 1 },
    })
    api.outline.listFusionSuggestions.mockResolvedValue({
      total: 1,
      items: [{
        id: "suggestion-1",
        source_scene_ids: ["s1", "s2"],
        chapter_span: [1, 3],
        proposed_scene: { title: "跨章追击" },
        status: "pending",
      }],
    })

    await sceneWorkbenchView._loadWorkbench()
    const html = await sceneWorkbenchView.render()

    expect(api.outline.listFusionSuggestions).toHaveBeenCalledWith(
      "p1",
      { skip: 0, limit: 100 },
    )
    expect(html).toContain("1 条 Scene 融合建议待处理")
    expect(html).toContain('data-action="dismiss-fusion-suggestions"')
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

  it("marks a scene as reviewed and organized while preserving structure meta", async () => {
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      items: workbenchPayload.items.map((item) => item.scene.id === "s1"
        ? {
            ...item,
            scene: {
              ...item.scene,
              structure_meta: {
                source_workflow_id: "wf-1",
                needs_review: true,
                needs_organize: true,
              },
            },
          }
        : item),
    }

    document.body.innerHTML = `<main id="workspace-content">${await sceneWorkbenchView.render()}</main>`
    sceneWorkbenchView._bindEvents()
    document.querySelector(".scene-workbench__organize").scrollTop = 84

    await sceneWorkbenchView._markSceneReviewed("s1")

    expect(api.outline.reviewSceneWorkbench).toHaveBeenCalledWith("p1", {
      scene_ids: ["s1"],
      decision: "review",
    })
    expect(toast).toHaveBeenCalledWith("Scene 已采用，仍有 2 项待处理", "warning")
    expect(router.refresh).not.toHaveBeenCalled()
    expect(document.querySelector(".scene-workbench__organize").scrollTop).toBe(84)
  })

  it("reviews selected scenes in bulk without resetting the scene list scroll", async () => {
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      items: workbenchPayload.items.map((item) => ({
        ...item,
        scene: {
          ...item.scene,
          structure_meta: {
            source_workflow_id: `wf-${item.scene.id}`,
            needs_review: true,
            needs_organize: true,
          },
        },
      })),
    }
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1", "s2"])
    document.body.innerHTML = `<main id="workspace-content">${await sceneWorkbenchView.render()}</main>`
    sceneWorkbenchView._bindEvents()
    document.querySelector(".scene-workbench__organize").scrollTop = 91

    await sceneWorkbenchView._reviewSelectedScenes()

    expect(api.outline.reviewSceneWorkbench).toHaveBeenCalledTimes(1)
    expect(api.outline.reviewSceneWorkbench).toHaveBeenCalledWith("p1", {
      scene_ids: ["s1", "s2"],
      decision: "review",
    })
    expect(sceneWorkbenchView._selectedFusionSceneIds.size).toBe(0)
    expect(toast).toHaveBeenCalledWith("已处理 2 个 Scene", "success")
    expect(router.refresh).not.toHaveBeenCalled()
    expect(document.querySelector(".scene-workbench__organize").scrollTop).toBe(91)
  })

  it("toggles selected reviewed scenes back to needing review", async () => {
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      items: workbenchPayload.items.map((item) => ({
        ...item,
        scene: {
          ...item.scene,
          structure_meta: {
            source_workflow_id: `wf-${item.scene.id}`,
            reviewed_at: "2026-07-05T00:00:00.000Z",
            reviewed_by: "manual",
            reviewed_from: "scene_workbench_bulk",
          },
        },
      })),
    }
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1", "s2"])
    document.body.innerHTML = `<main id="workspace-content">${await sceneWorkbenchView.render()}</main>`
    sceneWorkbenchView._bindEvents()
    document.querySelector(".scene-workbench__organize").scrollTop = 55

    await sceneWorkbenchView._toggleSelectedSceneReview()

    expect(api.outline.reviewSceneWorkbench).toHaveBeenCalledTimes(1)
    expect(api.outline.reviewSceneWorkbench).toHaveBeenCalledWith("p1", {
      scene_ids: ["s1", "s2"],
      decision: "reopen",
    })
    expect(sceneWorkbenchView._selectedFusionSceneIds.size).toBe(0)
    expect(toast).toHaveBeenCalledWith("已将 2 个 Scene 标记为需要人工检查", "success")
    expect(router.refresh).not.toHaveBeenCalled()
    expect(document.querySelector(".scene-workbench__organize").scrollTop).toBe(55)
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

    document.body.innerHTML = `<main id="workspace-content">${await sceneWorkbenchView.render()}</main>`
    sceneWorkbenchView._bindEvents()
    document.querySelector(".scene-workbench__organize").scrollTop = 73

    await sceneWorkbenchView._markSceneUnreviewed("s1")

    expect(api.outline.reviewSceneWorkbench).toHaveBeenCalledWith("p1", {
      scene_ids: ["s1"],
      decision: "reopen",
    })
    expect(toast).toHaveBeenCalledWith("Scene 已标记为需要人工检查", "success")
    expect(router.refresh).not.toHaveBeenCalled()
    expect(document.querySelector(".scene-workbench__organize").scrollTop).toBe(73)
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
      warnings: [
        "章节跨度较大",
        "AI 融合调用失败，已返回确定性融合草稿，请人工复核。",
      ],
    })
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1", "s2"])

    await sceneWorkbenchView._startManualFusion()
    expect(showModal.mock.calls[0][0]).toBe("选择主 Scene")
    document.body.innerHTML = showModal.mock.calls[0][1].html
    const keepPreviewOpen = await showModal.mock.calls[0][2][1].handler()

    expect(api.outline.previewSceneFusion).toHaveBeenCalledWith("p1", {
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
    })
    expect(keepPreviewOpen).toBe(false)
    expect(showModal).toHaveBeenCalled()
    expect(showModal.mock.calls[1][0]).toBe("AI 融合建议生成中")
    expect(modalHtmlFromCall(showModal.mock.calls[1])).toContain("正在读取精确正文证据")
    const call = showModal.mock.calls[2]
    const [title, , buttons] = call
    const body = modalHtmlFromCall(call)
    expect(title).toBe("Scene AI 建议预览")
    expect(body).toContain("潜入与撤离")
    expect(body).toContain("取得密信并撤离")
    expect(body).toContain("章节跨度较大")
    expect(body).toContain("AI 融合调用失败")
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

  it("prevents duplicate AI fusion previews while the synchronous call is pending", async () => {
    let resolvePreview
    api.outline.previewSceneFusion.mockReturnValue(new Promise((resolve) => {
      resolvePreview = resolve
    }))

    const pending = sceneWorkbenchView._previewFusionWithPrimary(["s1", "s2"], "s1")
    await sceneWorkbenchView._previewFusionWithPrimary(["s1", "s2"], "s1")

    expect(api.outline.previewSceneFusion).toHaveBeenCalledTimes(1)
    expect(showModal.mock.calls[0][0]).toBe("AI 融合建议生成中")
    resolvePreview({
      mode: "fusion",
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      draft_scene: { title: "融合草稿" },
      warnings: [],
    })
    await pending
    expect(sceneWorkbenchView._fusionPreviewPending).toBe(false)
  })

  it("discards an AI fusion response after the active project changes", async () => {
    let resolvePreview
    api.outline.previewSceneFusion.mockReturnValue(new Promise((resolve) => {
      resolvePreview = resolve
    }))

    const pending = sceneWorkbenchView._previewFusionWithPrimary(["s1", "s2"], "s1")
    resetState({ currentProjectId: "p2", currentView: "scene", currentSubView: "s1" })
    resolvePreview({
      mode: "fusion",
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      draft_scene: { title: "旧项目融合草稿" },
      warnings: [],
    })
    await pending

    expect(showModal).toHaveBeenCalledTimes(1)
    expect(sceneWorkbenchView._activeDraftReview).toBeNull()
    expect(sceneWorkbenchView._fusionPreviewPending).toBe(false)
  })

  it("does not save an existing fusion preview after the active project changes", async () => {
    sceneWorkbenchView._activeDraftReview = {
      request_project_id: "p1",
      primary_scene_id: "s1",
    }
    resetState({ currentProjectId: "p2", currentView: "scene", currentSubView: "s1" })

    await sceneWorkbenchView._saveFusionResult("keep_originals", ["s1", "s2"])

    expect(api.outline.saveSceneFusion).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(
      "项目已切换，请在当前项目重新生成融合建议",
      "warning",
    )
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

  it("carries the durable suggestion id into fusion save", async () => {
    api.outline.saveSceneFusion.mockResolvedValue({ status: "discarded" })
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._activeDraftReview = {
      primary_scene_id: "s1",
      suggestion_id: "suggestion-1",
    }

    await sceneWorkbenchView._saveFusionResult("discard", ["s1", "s2"])

    expect(api.outline.saveSceneFusion).toHaveBeenCalledWith("p1", {
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      mode: "discard",
      suggestion_id: "suggestion-1",
    })
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
    const call = showModal.mock.calls[0]
    const [, , buttons] = call
    const body = modalHtmlFromCall(call)
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

  it("keeps merge preview open and shows feedback when merge fails", async () => {
    api.outline.previewSceneMerge.mockResolvedValue({
      operation: "merge",
      chapter_mapping_change: { after: { s1: ["1", "2"] } },
      field_changes: {},
      warnings: ["只提示"],
    })
    api.outline.mergeScenes.mockRejectedValue(new Error("merge failed"))
    sceneWorkbenchView._workbench = workbenchPayload

    await sceneWorkbenchView._previewAndMerge("s1", ["s2"])
    const buttons = showModal.mock.calls[0][2]
    const result = await buttons.find((button) => button.text === "确认合并").handler()

    expect(result).toBe(false)
    expect(closeModal).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("Scene 合并失败：merge failed", "error")
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
    document.body.innerHTML = showModal.mock.calls[0][1].html
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
    const call = showModal.mock.calls[0]
    const [title, , buttons] = call
    const body = modalHtmlFromCall(call)
    expect(title).toBe("Scene AI 建议预览")
    expect(body).toContain("AI 拆分建议")
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

  it("keeps split preview open and shows feedback when split fails", async () => {
    api.outline.previewSceneSplit.mockResolvedValue({
      operation: "split",
      chapter_mapping_change: { after: { s1: ["1"] } },
      field_changes: {},
      warnings: [],
      draft_scenes: [
        { title: "前半", goal: "前半目标", chapter_ids: ["1"] },
        { title: "后半", goal: "后半目标", chapter_ids: ["2"] },
      ],
      field_references: {},
    })
    api.outline.splitScene.mockRejectedValue(new Error("split failed"))
    sceneWorkbenchView._workbench = workbenchPayload

    await sceneWorkbenchView._previewAndSplit("s1", 2)
    const call = showModal.mock.calls[0]
    document.body.innerHTML = modalHtmlFromCall(call)
    const result = await call[2].find((button) => button.text === "确认拆分").handler()

    expect(result).toBe(false)
    expect(closeModal).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("Scene 拆分失败：split failed", "error")
  })

  it("opens fusion suggestions through draft review instead of saving", async () => {
    showModal.mockReset()
    showModal.mockImplementation(() => {})
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._fusionSuggestions = [{
      source_scene_ids: ["s1", "s2"],
      chapter_span: [1, 3],
      confidence: 0.8,
      proposed_action: "merge",
      suggestion_kind: "cross_chapter",
      reason: "同一场追击",
      proposed_scene: { title: "跨章追击" },
      scan_trace: [],
    }]

    sceneWorkbenchView._showFusionSuggestions()
    const buttons = showModal.mock.calls[0][2]
    await buttons[0].handler()

    expect(api.outline.saveSceneFusion).not.toHaveBeenCalled()
    expect(showModal.mock.calls[1][0]).toBe("选择主 Scene")
  })

  it("handles keep-separate suggestions without opening fusion", async () => {
    showModal.mockReset()
    showModal.mockImplementation(() => {})
    api.outline.dismissFusionSuggestions.mockResolvedValue({ dismissed: 1 })
    const refresh = vi.spyOn(sceneWorkbenchView, "_refreshWorkbenchInPlace")
      .mockResolvedValue()
    sceneWorkbenchView._fusionSuggestions = [{
      id: "sg-keep",
      source_scene_ids: ["s1", "s2"],
      chapter_span: [1],
      confidence: 0.8,
      proposed_action: "keep_separate",
      suggestion_kind: "intra_chapter",
      reason: "两个独立目标",
      scan_trace: [],
    }]

    sceneWorkbenchView._showFusionSuggestions()
    await showModal.mock.calls[0][2][0].handler()

    expect(showModal.mock.calls[1][0]).toBe("保持 Scene 分开")
    expect(api.outline.previewSceneFusion).not.toHaveBeenCalled()
    await showModal.mock.calls[1][2][1].handler()
    expect(api.outline.dismissFusionSuggestions).toHaveBeenCalledWith("p1", {
      suggestion_ids: ["sg-keep"],
      confirmed: true,
    })
    expect(refresh).toHaveBeenCalled()
  })

  it("opens writing at the first mapped chapter", () => {
    sceneWorkbenchView._openWritingForScene({
      id: "s1",
      chapter_ids: ["3", "4"],
    })

    expect(state.viewStates.writing.currentChapter).toBe(3)
    expect(state.viewStates.writing.projectId).toBe("p1")
    expect(router.navigate).toHaveBeenCalledWith("writing", null)
  })

  it("keeps router subview and only closes mobile detail on leave", () => {
    state.currentSubView = "s1"
    sceneWorkbenchView._mobileDetailOpen = true

    sceneWorkbenchView.onLeave()

    expect(state.currentSubView).toBe("s1")
    expect(sceneWorkbenchView._mobileDetailOpen).toBe(false)
  })

  it("toasts and does not refresh workbench when saving scene details fails", async () => {
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
    api.outline.updateScene.mockRejectedValue(new Error("保存失败"))

    await sceneWorkbenchView._saveSceneDetails("s1")

    expect(api.outline.updateScene).toHaveBeenCalledWith("s1", "p1", expect.any(Object))
    expect(toast).toHaveBeenCalledWith("保存失败", "error")
    expect(router.refresh).not.toHaveBeenCalled()
  })
})
