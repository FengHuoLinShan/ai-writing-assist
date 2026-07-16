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
  api.outline.applySceneReplacement = vi.fn().mockResolvedValue({
    status: "adopted",
    result_scene_ids: ["new-scene"],
    downstream_refresh_required: ["world_objects", "plot_structure"],
  })
  api.outline.updateScene.mockResolvedValue({ id: "s1" })
  api.outline.deleteScene = vi.fn().mockResolvedValue(null)
  sceneWorkbenchView._loading = false
  sceneWorkbenchView._fusionPreviewPending = false
  sceneWorkbenchView._fusionPreviewProjectId = null
  sceneWorkbenchView._fusionPreviewRequestSeq = 0
  sceneWorkbenchView._fusionSavePending = false
  sceneWorkbenchView._fusionSaveControls = []
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
    segment: "",
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
  sceneWorkbenchView._viewMode = "hot"
  sceneWorkbenchView._mergeReferencePicker = null
  sceneWorkbenchView._mergePreviewRequestGeneration = 0
})

describe("Scene 工作台普通/热点模式", () => {
  it("无 URL 和历史偏好时默认热点并锚定最新剧情", async () => {
    state.currentView = "outline"
    state.currentSubView = "scenes"
    window.history.replaceState({}, "", "#workbench/p1/outline/scenes")
    api.outline.getSceneWorkbench.mockResolvedValue({
      ...workbenchPayload,
      selected_scene_id: null,
      progress: { as_of_chapter: 3, current: 1, upcoming: 0, past: 1, unassigned: 0 },
    })

    await sceneWorkbenchView.onEnter()

    expect(sceneWorkbenchView._viewMode).toBe("hot")
    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", null, {
      skip: 0,
      limit: 20,
      view_mode: "hot",
      anchor: "latest",
    })
  })

  it("URL 普通模式覆盖热点偏好且不请求进度锚点", async () => {
    state.currentView = "outline"
    state.currentSubView = "scenes"
    localStorage.setItem("novel_view_mode:p1:scene-workbench", "hot")
    window.history.replaceState({}, "", "#workbench/p1/outline/scenes?mode=normal")

    await sceneWorkbenchView.onEnter()

    expect(sceneWorkbenchView._viewMode).toBe("normal")
    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", null, {
      skip: 0,
      limit: 20,
      view_mode: "normal",
    })
  })

  it("热点进度可按阶段筛选并清理当前选择", async () => {
    state.currentView = "outline"
    state.currentSubView = "scenes"
    window.history.replaceState({}, "", "#workbench/p1/outline/scenes?mode=hot&scene_id=s1")
    sceneWorkbenchView._viewMode = "hot"
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      progress: { as_of_chapter: 3, current: 1, upcoming: 1, past: 0, unassigned: 0 },
    }
    api.outline.getSceneWorkbench.mockResolvedValue(sceneWorkbenchView._workbench)

    const html = await sceneWorkbenchView.render()
    expect(html).toContain("当前剧情定位")
    expect(html).toContain("截至第 3 章")

    await sceneWorkbenchView._toggleProgressSegment("upcoming")

    expect(window.location.hash).toBe("#workbench/p1/outline/scenes?mode=hot")
    expect(api.outline.getSceneWorkbench).toHaveBeenLastCalledWith("p1", null, {
      skip: 0,
      limit: 20,
      view_mode: "hot",
      segment: "upcoming",
    })
  })

  it("模式切换保留通用筛选并按项目页面记忆", async () => {
    state.currentView = "outline"
    state.currentSubView = "scenes"
    window.history.replaceState({}, "", "#workbench/p1/outline/scenes?mode=hot&scene_id=s1")
    sceneWorkbenchView._viewMode = "hot"
    sceneWorkbenchView._filters = {
      ...sceneWorkbenchView._filters,
      q: "潜入",
      segment: "current",
      skip: 20,
    }
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1"])

    await sceneWorkbenchView._setViewMode("normal")

    expect(localStorage.getItem("novel_view_mode:p1:scene-workbench")).toBe("normal")
    expect(sceneWorkbenchView._filters.q).toBe("潜入")
    expect(sceneWorkbenchView._filters.segment).toBe("")
    expect(sceneWorkbenchView._filters.skip).toBe(0)
    expect(sceneWorkbenchView._selectedFusionSceneIds.size).toBe(0)
    const query = router.navigate.mock.calls.at(-1)[3]
    expect(query.get("mode")).toBe("normal")
    expect(query.get("scene_id")).toBe(null)
  })
})

describe("sceneWorkbenchView", () => {
  it("renders an accessible skeleton while the workbench is loading", async () => {
    sceneWorkbenchView._loading = true

    const html = await sceneWorkbenchView.render()

    expect(html).toContain("场景工作台加载中")
    expect(html).toContain('class="loading-skeleton"')
    expect(html).toContain('role="status"')
  })

  it("renders scene auto extraction action", async () => {
    sceneWorkbenchView._workbench = workbenchPayload

    const html = await sceneWorkbenchView.render()

    expect(html).toContain("scene-workbench-shell")
    expect(html).not.toContain("scene-workbench-actions")
    const headerActions = sceneWorkbenchView.renderHeaderActions()
    expect(headerActions).toContain("场景（scene）自动提取")
    expect(headerActions).toContain('data-action="scene-auto-extract"')
    expect(headerActions).toContain('data-role="smart-dedup-action"')
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
    expect(html).toContain("<span>#1</span>")
    expect(html).not.toContain("<span>#0</span>")
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
    expect(window.location.hash).toBe("#workbench/p1/scene/s2?mode=hot")
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
    expect(window.location.hash).toBe("#workbench/p1/outline/scenes?mode=hot&scene_id=s2")
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

    expect(sceneWorkbenchView._selectedSceneId()).toBeNull()
    expect(sceneWorkbenchView._selectedSceneItem()).toBeNull()
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
      view_mode: "hot",
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
      view_mode: "hot",
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
      view_mode: "hot",
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
      view_mode: "hot",
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
      view_mode: "hot",
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
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      health: {
        ...workbenchPayload.health,
        needs_organize: {
          ...workbenchPayload.health.needs_organize,
          breakdown: { scene_structure: 1, source_mapping: 1 },
        },
      },
    }

    const html = await sceneWorkbenchView.render()

    expect(html).toContain("scene-workbench")
    expect(html).toContain("scene-workbench__organize")
    expect(html).toContain("scene-workbench__detail")
    expect(html).toContain("未复核")
    expect(html).toContain("未关联章节")
    expect(html).toContain("缺设定")
    expect(html).toContain("待整理")
    expect(html).toContain("待整理总数按 Scene 去重")
    expect(html).toContain("原因数不能相加作为总数")
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

  it("在 Scene 卡片和详情中显示作者可读正文范围与重叠细节", async () => {
    const counterpartId = "22222222-2222-4222-8222-222222222222"
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      items: [
        {
          ...workbenchPayload.items[0],
          span_summaries: [
            {
              chapter_index: 1,
              mapping_status: "exact",
              mapping_status_label: "精确定位",
              anchor_excerpt: "枪声响起 众人开始追逐",
              range_label: "第 1 章 · 字符 10–50 · 精确定位",
            },
            {
              chapter_index: 3,
              mapping_status: "chapter_only",
              mapping_status_label: "仅关联章节",
              range_label: "第 3 章 · 第 1–3 段",
            },
          ],
          overlap_details: [{
            counterpart_scene_id: counterpartId,
            counterpart_scene_title: "追逐转折",
            counterpart_scene_label: "追逐转折",
            chapter_index: 1,
            scene_start_offset: 10,
            scene_end_offset: 50,
            counterpart_start_offset: 40,
            counterpart_end_offset: 80,
            overlap_start_offset: 40,
            overlap_end_offset: 50,
            range_label: "第 1 章 · 字符 40–50 与「追逐转折」重叠",
          }],
        },
        {
          ...workbenchPayload.items[1],
          scene: {
            ...workbenchPayload.items[1].scene,
            id: counterpartId,
            title: "追逐转折",
          },
        },
      ],
    }

    document.body.innerHTML = await sceneWorkbenchView.render()
    const text = document.body.textContent

    expect(text).toContain("第 1 章 · 字符 10–50 · 精确定位")
    expect(text).toContain("第 3 章 · 第 1–3 段 · 仅关联章节")
    expect(text).toContain("原文摘要：枪声响起 众人开始追逐")
    expect(text).toContain("第 1 章 · 字符 40–50 与「追逐转折」重叠")
    expect(text).toContain("当前范围：第 1 章 · 字符 10–50")
    expect(text).toContain("对方范围：第 1 章 · 字符 40–80")
    expect(text).toContain("实际重叠：第 1 章 · 字符 40–50")
    expect(text).toContain("查看「追逐转折」")
    expect(text).not.toContain(counterpartId)
    expect(document.querySelector('[data-action="open-overlap-scene"]').dataset.id).toBe(counterpartId)
  })

  it("重叠对方在当前列表时可直接查看且不显示 UUID", async () => {
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      items: [
        {
          ...workbenchPayload.items[0],
          overlap_details: [{
            counterpart_scene_id: "s2",
            counterpart_scene_title: "撤离",
            counterpart_scene_label: "撤离",
            chapter_index: 1,
            scene_start_offset: 0,
            scene_end_offset: 20,
            counterpart_start_offset: 10,
            counterpart_end_offset: 30,
            overlap_start_offset: 10,
            overlap_end_offset: 20,
            range_label: "第 1 章 · 字符 10–20 与「撤离」重叠",
          }],
        },
        workbenchPayload.items[1],
      ],
    }
    document.body.innerHTML = `<main id="workspace-content">${await sceneWorkbenchView.render()}</main>`
    sceneWorkbenchView._bindEvents()

    document.querySelector('[data-action="open-overlap-scene"]').click()

    expect(state.currentSubView).toBe("s2")
    expect(window.location.hash).toBe("#workbench/p1/scene/s2?mode=hot")
    expect(document.body.textContent).not.toContain("s2")
  })

  it("重叠对方不在当前页时重置筛选后打开", async () => {
    sceneWorkbenchView._filters = {
      ...sceneWorkbenchView._filters,
      health: "needs_organize",
      q: "当前页关键词",
      skip: 20,
    }
    sceneWorkbenchView._activeHealth = "needs_organize"
    router.refresh.mockResolvedValue()

    expect(await sceneWorkbenchView._openOverlapScene("off-page-scene")).toBe(true)

    expect(sceneWorkbenchView._filters.health).toBe("")
    expect(sceneWorkbenchView._filters.q).toBe("")
    expect(sceneWorkbenchView._filters.skip).toBe(0)
    expect(sceneWorkbenchView._activeHealth).toBeNull()
    expect(state.currentSubView).toBe("off-page-scene")
    expect(router.refresh).toHaveBeenCalledOnce()
  })

  it("旧 workbench 响应没有 overlap detail 时保留旧待处理提示", async () => {
    sceneWorkbenchView._workbench = {
      ...workbenchPayload,
      items: [{
        ...workbenchPayload.items[0],
        health: ["needs_organize"],
        health_details: {
          needs_organize: [{
            code: "overlapping_span",
            label: "正文范围与其他 Scene 重叠",
          }],
        },
      }],
    }

    const html = await sceneWorkbenchView.render()

    expect(html).toContain("正文范围与其他 Scene 重叠")
    expect(html).not.toContain("scene-detail-overlaps")
    expect(html).not.toContain('data-action="open-overlap-scene"')
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
      { skip: 0, limit: 50 },
    )
    expect(html).toContain("1 条 Scene 建议待处理")
    expect(html).toContain('data-action="dismiss-fusion-suggestions"')
  })

  it("loads persisted fusion suggestions through the bounded API pages", async () => {
    api.outline.getSceneWorkbench.mockResolvedValue({
      ...workbenchPayload,
      fusion_suggestions: { pending_count: 51 },
    })
    const firstPage = Array.from({ length: 50 }, (_, index) => ({
      id: `suggestion-${index + 1}`,
      suggestion_kind: "fusion",
    }))
    api.outline.listFusionSuggestions
      .mockResolvedValueOnce({ total: 51, items: firstPage })
      .mockResolvedValueOnce({
        total: 51,
        items: [{ id: "suggestion-51", suggestion_kind: "replacement" }],
      })

    await sceneWorkbenchView._loadWorkbench()

    expect(api.outline.listFusionSuggestions.mock.calls).toEqual([
      ["p1", { skip: 0, limit: 50 }],
      ["p1", { skip: 50, limit: 50 }],
    ])
    expect(sceneWorkbenchView._fusionSuggestions).toHaveLength(51)
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

  it("clears a stale embedded selection when a saved scene leaves the active filter", async () => {
    state.currentView = "outline"
    state.currentSubView = "scenes"
    window.history.replaceState(
      { view: "outline", subView: "scenes", projectId: "p1" },
      "",
      "#workbench/p1/outline/scenes?scene_id=s1",
    )
    sceneWorkbenchView._filters.health = "unreviewed"
    sceneWorkbenchView._workbench = workbenchPayload
    const missingSelection = new Error("请求的资源不存在：Scene not found")
    missingSelection.status = 404
    missingSelection.detail = "Scene not found"
    api.outline.getSceneWorkbench
      .mockRejectedValueOnce(missingSelection)
      .mockResolvedValueOnce({
        ...workbenchPayload,
        total: 1,
        selected_scene_id: "s2",
        items: [workbenchPayload.items[1]],
      })
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

    await sceneWorkbenchView._saveSceneDetails("s1")

    expect(api.outline.getSceneWorkbench.mock.calls.slice(-2)).toEqual([
      ["p1", "s1", { health: "unreviewed", skip: 0, limit: 20, view_mode: "hot" }],
      ["p1", null, { health: "unreviewed", skip: 0, limit: 20, view_mode: "hot" }],
    ])
    expect(window.location.hash).toBe("#workbench/p1/outline/scenes")
    expect(toast).toHaveBeenCalledWith("Scene 已保存", "success")
    expect(toast).not.toHaveBeenCalledWith(
      "请求的资源不存在：Scene not found",
      "error",
    )
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

  it("shows move to history only for active scene rows", () => {
    const activeHtml = sceneWorkbenchView._renderSceneRow(workbenchPayload.items[0], "s1")
    const historyHtml = sceneWorkbenchView._renderSceneRow({
      ...workbenchPayload.items[0],
      scene: {
        ...workbenchPayload.items[0].scene,
        status: "deprecated",
      },
    }, "s1")

    expect(activeHtml).toContain('data-action="move-scene-to-history"')
    expect(activeHtml).toContain("移入历史")
    expect(historyHtml).not.toContain('data-action="move-scene-to-history"')
  })

  it("keeps a scene unchanged when moving to history is cancelled", async () => {
    document.body.innerHTML = `
      <div id="modal-overlay"></div>
      <button id="modal-close"></button>
      <div id="modal-footer"></div>
    `
    confirmAction.mockImplementation(() => {
      const cancel = document.createElement("button")
      cancel.textContent = "取消"
      document.getElementById("modal-footer").appendChild(cancel)
    })
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1"])

    const pending = sceneWorkbenchView._moveSceneToHistory("s1")
    document.querySelector("#modal-footer button").click()
    const moved = await pending

    expect(moved).toBe(false)
    expect(api.outline.deleteScene).not.toHaveBeenCalled()
    expect(sceneWorkbenchView._selectedFusionSceneIds).toEqual(new Set(["s1"]))
  })

  it("moves the selected scene to history and clears its route and selection", async () => {
    state.currentView = "outline"
    state.currentSubView = "scenes"
    window.history.replaceState(
      { view: "outline", subView: "scenes", projectId: "p1" },
      "",
      "#workbench/p1/outline/scenes?scene_id=s1",
    )
    autoConfirm()
    api.outline.deleteScene.mockResolvedValue(null)
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1", "s2"])
    const refresh = vi.spyOn(sceneWorkbenchView, "_refreshWorkbenchInPlace")
      .mockResolvedValue()

    const moved = await sceneWorkbenchView._moveSceneToHistory("s1")

    expect(moved).toBe(true)
    expect(confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("正文和追踪信息会保留"),
      expect.any(Function),
      "确认移入历史",
    )
    expect(api.outline.deleteScene).toHaveBeenCalledWith("s1", "p1")
    expect(sceneWorkbenchView._selectedFusionSceneIds).toEqual(new Set(["s2"]))
    expect(window.location.hash).toBe("#workbench/p1/outline/scenes")
    expect(toast).toHaveBeenCalledWith("Scene 已移入历史", "success")
    expect(refresh).toHaveBeenCalled()
  })

  it("preserves scene state when moving to history fails", async () => {
    state.currentView = "outline"
    state.currentSubView = "scenes"
    window.history.replaceState(
      { view: "outline", subView: "scenes", projectId: "p1" },
      "",
      "#workbench/p1/outline/scenes?scene_id=s1",
    )
    autoConfirm()
    api.outline.deleteScene.mockRejectedValue(new Error("删除请求失败"))
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._selectedFusionSceneIds = new Set(["s1"])
    const refresh = vi.spyOn(sceneWorkbenchView, "_refreshWorkbenchInPlace")
      .mockResolvedValue()

    const moved = await sceneWorkbenchView._moveSceneToHistory("s1")

    expect(moved).toBe(false)
    expect(sceneWorkbenchView._selectedFusionSceneIds).toEqual(new Set(["s1"]))
    expect(window.location.hash).toContain("scene_id=s1")
    expect(refresh).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("移入历史失败：删除请求失败", "error")
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
    expect(body).toContain("scene-fusion-narrative-tag")
    expect(body).toContain("scene-fusion-pov")
    expect(body).toContain("<table")
    expect(buttons.map((button) => button.text)).toEqual([
      "关闭",
      "放弃融合结果（标记不采用）",
      "继续编辑融合结果后再保存",
      "废弃 2 个原 Scene 并保存",
      "保留原 Scene + 保存融合 Scene",
    ])
    expect(call[3]).toEqual({ size: "large" })
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
    ["放弃融合结果（标记不采用）", "discard"],
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
        narrative_tag: "draft",
        pov_character_id: null,
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

  it("requires an inline second confirmation before deprecating fusion sources", async () => {
    const preview = {
      mode: "fusion",
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      draft_scene: { title: "融合草稿", chapter_ids: ["1", "2"] },
      source_scene_summaries: [
        { id: "s1", title: "潜入", chapter_range: "第 1 章" },
        { id: "s2", title: "撤离", chapter_range: "第 2 章" },
      ],
      field_references: {},
      warnings: [],
    }
    api.outline.saveSceneFusion.mockResolvedValue({ status: "saved" })
    vi.spyOn(sceneWorkbenchView, "_refreshWorkbenchInPlace").mockResolvedValue()

    sceneWorkbenchView._showFusionPreview(preview, ["s1", "s2"])
    const call = showModal.mock.calls[0]
    document.body.innerHTML = `<div id="modal-body">${modalHtmlFromCall(call)}</div>`
    sceneWorkbenchView._bindDraftReviewModal({ sourceSceneIds: ["s1", "s2"] })

    const firstResult = await call[2]
      .find((button) => button.text === "废弃 2 个原 Scene 并保存")
      .handler()

    expect(firstResult).toBe(false)
    expect(api.outline.saveSceneFusion).not.toHaveBeenCalled()
    const confirmation = document.querySelector('[data-role="fusion-deprecation-confirm"]')
    expect(confirmation.hidden).toBe(false)
    expect(confirmation.textContent).toContain("潜入")
    expect(confirmation.textContent).toContain("撤离")

    document.querySelector('[data-action="confirm-fusion-deprecation"]').click()
    await vi.waitFor(() => expect(api.outline.saveSceneFusion).toHaveBeenCalledTimes(1))
    expect(api.outline.saveSceneFusion).toHaveBeenCalledWith("p1", expect.objectContaining({
      mode: "deprecate_originals",
      source_scene_ids: ["s1", "s2"],
    }))
  })

  it("normalizes fallback source ids into the preview and deprecation confirmation", () => {
    const preview = {
      mode: "fusion",
      primary_scene_id: "s1",
      draft_scene: { title: "融合草稿", narrative_tag: null },
      source_scene_summaries: [
        { id: "s1", title: "潜入", chapter_range: "第 1 章" },
        { id: "s2", title: "撤离", chapter_range: "第 2 章" },
      ],
      field_references: {
        narrative_tag: [{ scene_id: "s1", title: "潜入", value: "draft", role: "primary" }],
      },
    }

    sceneWorkbenchView._showFusionPreview(preview, ["s1", "s2"])

    const body = modalHtmlFromCall(showModal.mock.calls[0])
    document.body.innerHTML = `<div id="modal-body">${body}</div>`
    const tagRow = document.getElementById("scene-fusion-narrative-tag").closest("tr")
    expect(body).toContain("确认废弃 2 个原 Scene")
    expect(body).toContain("潜入")
    expect(body).toContain("撤离")
    expect(body).not.toContain('<option value=""')
    expect(tagRow.dataset.difference).toBe("false")
    expect(sceneWorkbenchView._activeDraftReview.source_scene_ids).toEqual(["s1", "s2"])
  })

  it("allows only one fusion save request while the first request is pending", async () => {
    let resolveSave
    api.outline.saveSceneFusion.mockReturnValue(new Promise((resolve) => {
      resolveSave = resolve
    }))
    vi.spyOn(sceneWorkbenchView, "_refreshWorkbenchInPlace").mockResolvedValue()
    const preview = {
      mode: "fusion",
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      draft_scene: { title: "融合草稿", chapter_ids: ["1", "2"] },
      field_references: {},
    }

    sceneWorkbenchView._showFusionPreview(preview, ["s1", "s2"])
    const call = showModal.mock.calls[0]
    const buttons = call[2]
    document.body.innerHTML = `
      <div id="modal-body">${modalHtmlFromCall(call)}</div>
      <div id="modal-footer">${buttons.map((button) => `<button>${button.text}</button>`).join("")}</div>
    `
    sceneWorkbenchView._bindDraftReviewModal({ sourceSceneIds: ["s1", "s2"] })
    buttons.find((button) => button.text.startsWith("废弃 2 个")).handler()
    const confirm = document.querySelector('[data-action="confirm-fusion-deprecation"]')

    confirm.click()
    confirm.click()
    const competingResult = await buttons
      .find((button) => button.text === "保留原 Scene + 保存融合 Scene")
      .handler()

    expect(competingResult).toBe(false)
    expect(api.outline.saveSceneFusion).toHaveBeenCalledTimes(1)
    expect(confirm.disabled).toBe(true)
    expect(Array.from(document.querySelectorAll("#modal-footer button")).every((button) => button.disabled)).toBe(true)

    resolveSave({ status: "saved" })
    await vi.waitFor(() => expect(sceneWorkbenchView._fusionSavePending).toBe(false))
    expect(confirm.disabled).toBe(false)
  })

  it("filters only initial differences while keeping no-evidence rows visible", () => {
    const preview = {
      mode: "fusion",
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      draft_scene: {
        title: "同名",
        goal: "融合目标",
        core_conflict: "相同冲突",
        narrative_tag: "draft",
        chapter_ids: ["1"],
      },
      field_references: {
        title: [
          { scene_id: "s1", title: "主", value: "同名", role: "primary" },
          { scene_id: "s2", title: "其他", value: "同名", role: "source" },
        ],
        goal: [{ scene_id: "s1", title: "主", value: "原目标", role: "primary" }],
        core_conflict: [{ scene_id: "s1", title: "主", value: "相同冲突", role: "primary" }],
      },
      conflicts: [{ field: "core_conflict", message: "冲突字段需复核" }],
    }
    const body = sceneWorkbenchView._renderDraftReview(preview)
    document.body.innerHTML = `<div id="modal-body">${body}</div>`
    sceneWorkbenchView._bindDraftReviewModal()

    const checkbox = document.querySelector('[data-action="filter-draft-review-differences"]')
    checkbox.checked = true
    checkbox.dispatchEvent(new Event("change"))
    const rows = Array.from(document.querySelectorAll(".scene-draft-review-row"))
    const rowFor = (label) => rows.find((row) => row.querySelector("th")?.textContent.includes(label))

    expect(rowFor("标题").hidden).toBe(true)
    expect(rowFor("目标").hidden).toBe(false)
    expect(rowFor("核心冲突").hidden).toBe(false)
    expect(rowFor("叙事标签").hidden).toBe(false)
    expect(rowFor("叙事标签").dataset.noEvidence).toBe("true")
    expect(document.querySelector('[data-role="draft-review-filter-note"]').textContent).toContain("仍会随草稿保存")
  })

  it("uses source summaries and collapses only long source evidence", () => {
    const longEvidence = "长来源证据。".repeat(30)
    const body = sceneWorkbenchView._renderDraftReview({
      mode: "fusion",
      source_scene_ids: ["s1", "s2"],
      primary_scene_id: "s1",
      source_scene_summaries: [
        { id: "s1", title: "主场景标题", chapter_range: "第 1 章" },
        { id: "s2", title: "来源场景标题", chapter_range: "第 2 章" },
      ],
      draft_scene: { must_happen: "AI 建议全文", chapter_ids: ["1", "2"] },
      field_references: {
        must_happen: [{ scene_id: "s1", title: "主场景标题", value: longEvidence, role: "primary" }],
      },
    })

    expect(body).toContain("主场景标题 · 第 1 章")
    expect(body).toContain("来源场景标题 · 第 2 章")
    expect(body).toContain('class="scene-draft-ref scene-draft-ref--long"')
    expect(body).toContain('id="scene-fusion-must"')
    expect(body).toContain("AI 建议全文")
  })

  it("escapes dynamic draft review summaries, warnings, conflicts, and references", () => {
    const attack = '<img src=x onerror="alert(1)">'
    const body = sceneWorkbenchView._renderDraftReview({
      mode: "fusion",
      source_scene_ids: ["s1"],
      primary_scene_id: "s1",
      source_scene_summaries: [{ id: "s1", title: attack, chapter_range: attack }],
      draft_scene: { title: attack, chapter_ids: ["1"] },
      field_references: {
        title: [{ scene_id: "s1", title: attack, value: attack, role: "primary" }],
      },
      warnings: [attack],
      conflicts: [{ field: "title", message: attack }],
    })

    expect(body).not.toContain(attack)
    expect(body).toContain("&lt;img")
    expect(body).not.toContain("onerror=\"alert(1)\"")
  })

  it("keeps the real modal wrapper open and restores controls when saving fails", async () => {
    const previousModalGlobals = {
      showModal: globalThis.showModal,
      showModalHtml: globalThis.showModalHtml,
      closeModal: globalThis.closeModal,
      confirmAction: globalThis.confirmAction,
    }
    try {
      vi.resetModules()
      await import("../ui/modal.js")
      api.outline.saveSceneFusion.mockRejectedValue(new Error("save failed"))
      document.body.innerHTML = `
        <div id="modal-overlay" class="hidden">
          <div id="modal-content">
            <h2 id="modal-title"></h2>
            <div id="modal-body"></div>
            <div id="modal-footer"></div>
          </div>
        </div>
      `
      sceneWorkbenchView._showFusionPreview({
        mode: "fusion",
        source_scene_ids: ["s1", "s2"],
        primary_scene_id: "s1",
        draft_scene: { title: "初始标题", chapter_ids: ["1"] },
        field_references: {},
      }, ["s1", "s2"])
      document.getElementById("scene-fusion-title").value = "保留的编辑"
      const saveButton = Array.from(document.querySelectorAll("#modal-footer button"))
        .find((button) => button.textContent === "保留原 Scene + 保存融合 Scene")

      saveButton.click()

      await vi.waitFor(() => expect(toast).toHaveBeenCalledWith("save failed", "error"))
      expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
      expect(document.getElementById("scene-fusion-title").value).toBe("保留的编辑")
      expect(saveButton.disabled).toBe(false)
    } finally {
      Object.assign(globalThis, previousModalGlobals)
    }
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
        narrative_tag: "transition",
        pov_character_id: "char-old",
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
    document.getElementById("scene-fusion-narrative-tag").value = "climax"
    document.getElementById("scene-fusion-pov").value = "char-new"
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
        narrative_tag: "climax",
        pov_character_id: "char-new",
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

  it("单行合并通过名称选择 Scene，并继续提交原有 ID payload", async () => {
    sceneWorkbenchView._workbench = workbenchPayload
    api.outline.getSceneWorkbench.mockResolvedValue({
      items: [{
        scene: {
          id: "s2",
          title: "潜入王宫",
          status: "canonical",
          chapter_ids: ["2"],
          goal: "取得密信",
        },
      }],
      total: 1,
    })
    api.outline.previewSceneMerge.mockResolvedValue({
      operation: "merge",
      chapter_mapping_change: {},
      field_changes: {},
      warnings: [],
    })
    document.body.innerHTML = '<div id="scene-merge-reference-picker"></div>'

    await sceneWorkbenchView._startMerge("s1")
    const query = document.querySelector("[data-reference-query]")
    query.value = "王宫"
    query.dispatchEvent(new Event("input"))
    await new Promise((resolve) => setTimeout(resolve, 230))
    document.querySelector("[data-reference-result]").click()
    const buttons = showModal.mock.calls[0][2]
    await buttons.find((button) => button.text === "预览合并影响").handler()

    expect(showModal.mock.calls[0][0]).toBe("选择要合并的 Scene")
    expect(showModal.mock.calls[0][1].html).not.toContain("Scene ID")
    expect(api.outline.previewSceneMerge).toHaveBeenCalledWith("p1", {
      target_scene_id: "s1",
      source_scene_ids: ["s2"],
    })
  })

  it("项目切换后丢弃晚到的合并预览，不打开旧项目弹窗", async () => {
    let resolvePreview
    api.outline.previewSceneMerge.mockImplementation(() => new Promise((resolve) => {
      resolvePreview = resolve
    }))

    const pending = sceneWorkbenchView._previewAndMerge("s1", ["s2"])
    state.currentProjectId = "p2"
    sceneWorkbenchView.onLeave()
    resolvePreview({
      operation: "merge",
      chapter_mapping_change: {},
      field_changes: {},
      warnings: [],
    })

    await expect(pending).resolves.toBe(false)
    expect(api.outline.previewSceneMerge).toHaveBeenCalledWith("p1", {
      target_scene_id: "s1",
      source_scene_ids: ["s2"],
    })
    expect(showModal).not.toHaveBeenCalled()
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
        { title: "前半", goal: "前半目标", narrative_tag: "hook", pov_character_id: "char-a", chapter_ids: ["1"], scene_chunks: [{ chapter_id: "1" }] },
        { title: "后半", goal: "后半目标", narrative_tag: "transition", pov_character_id: "char-b", chapter_ids: ["2"] },
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
    expect(body).toContain("scene-split-0-narrative_tag")
    expect(body).toContain("scene-split-0-pov_character_id")
    expect(body).toContain('<option value="hook" selected>')
    expect(body).not.toContain('<option value=""')
    expect(body).toContain("影响摘要")
    expect(body).toContain("建议 A 1 段")
    expect(call[3]).toEqual({ size: "large" })
    document.body.innerHTML = `<div id="modal-body">${body}</div>`
    sceneWorkbenchView._bindDraftReviewModal()
    document.getElementById("scene-split-0-title").value = "用户前半"
    document.getElementById("scene-split-1-title").value = "用户后半"
    document.getElementById("scene-split-0-narrative_tag").value = "draft"
    document.getElementById("scene-split-0-pov_character_id").value = ""
    expect(document.getElementById("scene-split-0-narrative_tag").value).toBe("draft")

    await buttons[1].handler()

    expect(api.outline.splitScene).toHaveBeenCalledWith("p1", {
      source_scene_id: "s1",
      split_chapter_index: 2,
      draft_scenes: [
        { title: "用户前半", goal: "前半目标", narrative_tag: "draft", pov_character_id: null },
        { title: "用户后半", goal: "后半目标", narrative_tag: "transition", pov_character_id: "char-b" },
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
      id: "sg-merge",
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
    document.body.innerHTML = modalHtmlFromCall(showModal.mock.calls[0])
    document.querySelector('input[name="review-suggestion"]').checked = true
    const buttons = showModal.mock.calls[0][2]
    const result = await buttons.find((button) => button.text === "处理所选审查").handler()

    expect(api.outline.saveSceneFusion).not.toHaveBeenCalled()
    expect(showModal.mock.calls[1][0]).toBe("选择主 Scene")
    expect(result).toBe(false)
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
    document.body.innerHTML = modalHtmlFromCall(showModal.mock.calls[0])
    document.querySelector('input[name="keep-separate-suggestion"]').checked = true
    const result = await showModal.mock.calls[0][2]
      .find((button) => button.text === "确认所选保持分开").handler()

    expect(showModal.mock.calls[1][0]).toBe("保持 Scene 分开")
    expect(api.outline.previewSceneFusion).not.toHaveBeenCalled()
    await showModal.mock.calls[1][2][1].handler()
    expect(api.outline.dismissFusionSuggestions).toHaveBeenCalledWith("p1", {
      suggestion_ids: ["sg-keep"],
      confirmed: true,
    })
    expect(refresh).toHaveBeenCalled()
    expect(result).toBe(false)
  })

  it("separates batch-safe suggestions from suggestions requiring review", () => {
    showModal.mockReset()
    showModal.mockImplementation(() => {})
    const attack = '<img src=x onerror="alert(1)">'
    sceneWorkbenchView._fusionSuggestions = [
      {
        id: "sg-keep",
        proposed_action: "keep_separate",
        suggestion_kind: "cross_chapter",
        chapter_span: [1, 2],
        reason: attack,
      },
      {
        id: "sg-merge",
        proposed_action: "merge",
        suggestion_kind: "cross_chapter",
        chapter_span: [2, 3],
        reason: "连续场景",
      },
      {
        id: "sg-review",
        proposed_action: "needs_review",
        suggestion_kind: "duplicate_window",
        chapter_span: [3, 4],
        reason: "LLMInvalidResponseError",
      },
    ]

    sceneWorkbenchView._showFusionSuggestions()

    const html = modalHtmlFromCall(showModal.mock.calls[0])
    expect(html).toContain("可批量确认保持分开")
    expect(html).toContain("需逐条审查")
    expect(html).toContain("Scene 切分建议")
    expect(html).toContain("Scene 融合建议")
    expect(html).toContain('type="checkbox" name="keep-separate-suggestion"')
    expect(html).toContain('type="radio" name="review-suggestion"')
    document.body.innerHTML = html
    expect(document.querySelectorAll('input[name="review-suggestion"]')).toHaveLength(2)
    expect(html).not.toContain(attack)
    expect(html).toContain("&lt;img")
  })

  it("keeps the queue open when neither batch nor review selection is made", async () => {
    showModal.mockReset()
    showModal.mockImplementation(() => {})
    sceneWorkbenchView._fusionSuggestions = [
      {
        id: "sg-keep",
        proposed_action: "keep_separate",
        suggestion_kind: "cross_chapter",
      },
      {
        id: "sg-merge",
        proposed_action: "merge",
        suggestion_kind: "cross_chapter",
      },
    ]

    sceneWorkbenchView._showFusionSuggestions()
    document.body.innerHTML = modalHtmlFromCall(showModal.mock.calls[0])
    const [confirmBatch, processReview] = showModal.mock.calls[0][2]

    expect(await confirmBatch.handler()).toBe(false)
    expect(await processReview.handler()).toBe(false)
    expect(showModal).toHaveBeenCalledTimes(1)
    expect(toast).toHaveBeenCalledWith("请先选择要确认保持分开的建议", "warning")
    expect(toast).toHaveBeenCalledWith("请先选择一条需逐条审查的建议", "warning")
  })

  it("deduplicates selected keep-separate ids and refreshes once", async () => {
    showModal.mockReset()
    showModal.mockImplementation(() => {})
    api.outline.dismissFusionSuggestions.mockResolvedValue({ dismissed: 2 })
    const refresh = vi.spyOn(sceneWorkbenchView, "_refreshWorkbenchInPlace")
      .mockResolvedValue()
    sceneWorkbenchView._fusionSuggestions = [
      { id: "sg-1", proposed_action: "keep_separate", suggestion_kind: "cross_chapter" },
      { id: "sg-2", proposed_action: "keep_separate", suggestion_kind: "intra_chapter" },
    ]

    sceneWorkbenchView._showFusionSuggestions()
    document.body.innerHTML = `${modalHtmlFromCall(showModal.mock.calls[0])}
      <input type="checkbox" name="keep-separate-suggestion" value="sg-1" checked />`
    document.querySelectorAll('input[name="keep-separate-suggestion"]').forEach((input) => {
      input.checked = true
    })
    await showModal.mock.calls[0][2]
      .find((button) => button.text === "确认所选保持分开").handler()
    const result = await showModal.mock.calls[1][2][1].handler()

    expect(api.outline.dismissFusionSuggestions).toHaveBeenCalledWith("p1", {
      suggestion_ids: ["sg-1", "sg-2"],
      confirmed: true,
    })
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(toast).toHaveBeenCalledWith("已确认 2 条建议保持分开", "success")
    expect(result).toBe(true)
  })

  it("selects at most 100 keep-separate suggestions per batch", () => {
    showModal.mockReset()
    showModal.mockImplementation(() => {})
    sceneWorkbenchView._fusionSuggestions = Array.from({ length: 101 }, (_, index) => ({
      id: `sg-${index + 1}`,
      proposed_action: "keep_separate",
      suggestion_kind: "cross_chapter",
    }))

    sceneWorkbenchView._showFusionSuggestions()
    document.body.innerHTML = modalHtmlFromCall(showModal.mock.calls[0])
    sceneWorkbenchView._bindKeepSeparateSelectionLimit()
    document.getElementById("select-all-keep-separate").click()

    const selected = document.querySelectorAll('input[name="keep-separate-suggestion"]:checked')
    expect(selected).toHaveLength(100)
    expect(modalHtmlFromCall(showModal.mock.calls[0])).toContain("每批最多确认 100 条")

    const checkboxes = Array.from(
      document.querySelectorAll('input[name="keep-separate-suggestion"]'),
    )
    checkboxes.forEach((input) => { input.checked = false })
    checkboxes.slice(0, 100).forEach((input) => {
      input.checked = true
      input.dispatchEvent(new Event("change"))
    })
    checkboxes[100].checked = true
    checkboxes[100].dispatchEvent(new Event("change"))
    expect(checkboxes[100].checked).toBe(false)
    expect(toast).toHaveBeenCalledWith("每批最多确认 100 条建议", "warning")

    checkboxes.forEach((input) => { input.checked = true })
    const result = showModal.mock.calls[0][2]
      .find((button) => button.text === "确认所选保持分开").handler()
    expect(result).toBe(false)
    expect(showModal).toHaveBeenCalledTimes(1)
  })

  it("keeps the real confirmation visible after failure and retries the same ids once", async () => {
    const previousModalGlobals = {
      showModal: globalThis.showModal,
      showModalHtml: globalThis.showModalHtml,
      closeModal: globalThis.closeModal,
      confirmAction: globalThis.confirmAction,
    }
    let resolveRetry
    try {
      vi.resetModules()
      await import("../ui/modal.js")
      vi.spyOn(sceneWorkbenchView, "_refreshWorkbenchInPlace").mockResolvedValue()
      api.outline.dismissFusionSuggestions
        .mockRejectedValueOnce(new Error("dismiss failed"))
        .mockImplementationOnce(() => new Promise((resolve) => { resolveRetry = resolve }))
      document.body.innerHTML = `
        <div id="modal-overlay" class="hidden">
          <div id="modal-content">
            <h2 id="modal-title"></h2>
            <div id="modal-body"></div>
            <div id="modal-footer"></div>
          </div>
        </div>
      `
      sceneWorkbenchView._fusionSuggestions = [{
        id: "sg-keep",
        proposed_action: "keep_separate",
        suggestion_kind: "cross_chapter",
      }]
      sceneWorkbenchView._showFusionSuggestions()
      document.querySelector('input[name="keep-separate-suggestion"]').checked = true
      Array.from(document.querySelectorAll("#modal-footer button"))
        .find((button) => button.textContent === "确认所选保持分开").click()
      const confirmButton = Array.from(document.querySelectorAll("#modal-footer button"))
        .find((button) => button.textContent === "确认 1 条保持分开")

      confirmButton.click()
      await vi.waitFor(() => expect(toast).toHaveBeenCalledWith("dismiss failed", "error"))
      expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
      expect(confirmButton.disabled).toBe(false)
      expect(confirmButton.textContent).toBe("确认 1 条保持分开")

      confirmButton.click()
      confirmButton.click()
      expect(api.outline.dismissFusionSuggestions).toHaveBeenCalledTimes(2)
      expect(confirmButton.disabled).toBe(true)
      expect(confirmButton.textContent).toBe("确认中...")
      resolveRetry({ dismissed: 1 })

      await vi.waitFor(() => (
        expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(true)
      ))
      expect(api.outline.dismissFusionSuggestions).toHaveBeenNthCalledWith(1, "p1", {
        suggestion_ids: ["sg-keep"],
        confirmed: true,
      })
      expect(api.outline.dismissFusionSuggestions).toHaveBeenNthCalledWith(2, "p1", {
        suggestion_ids: ["sg-keep"],
        confirmed: true,
      })
    } finally {
      Object.assign(globalThis, previousModalGlobals)
    }
  })

  it("treats refresh failure after dismiss as a completed mutation", async () => {
    showModal.mockReset()
    showModal.mockImplementation(() => {})
    api.outline.dismissFusionSuggestions.mockResolvedValue({ dismissed: 2 })
    vi.spyOn(sceneWorkbenchView, "_refreshWorkbenchInPlace")
      .mockRejectedValue(new Error("refresh failed"))

    sceneWorkbenchView._confirmKeepSeparateSuggestions(["sg-1", "sg-2"])
    const result = await showModal.mock.calls[0][2][1].handler()

    expect(result).toBe(true)
    expect(api.outline.dismissFusionSuggestions).toHaveBeenCalledTimes(1)
    expect(toast).toHaveBeenCalledWith(
      "已确认 2 条建议，但工作台刷新失败，请手动刷新",
      "warning",
    )
    expect(toast).not.toHaveBeenCalledWith("refresh failed", "error")
  })

  it("keeps follow-up modals visible for keep, merge, and replacement suggestions", async () => {
    const previousModalGlobals = {
      showModal: globalThis.showModal,
      showModalHtml: globalThis.showModalHtml,
      closeModal: globalThis.closeModal,
      confirmAction: globalThis.confirmAction,
    }
    try {
      vi.resetModules()
      await import("../ui/modal.js")
      sceneWorkbenchView._workbench = workbenchPayload
      const cases = [
        {
          suggestion: {
            id: "sg-keep",
            proposed_action: "keep_separate",
            suggestion_kind: "cross_chapter",
          },
          selector: 'input[name="keep-separate-suggestion"]',
          buttonText: "确认所选保持分开",
          nextTitle: "保持 Scene 分开",
        },
        {
          suggestion: {
            id: "sg-merge",
            source_scene_ids: ["s1", "s2"],
            proposed_action: "merge",
            suggestion_kind: "cross_chapter",
          },
          selector: 'input[name="review-suggestion"]',
          buttonText: "处理所选审查",
          nextTitle: "选择主 Scene",
        },
        {
          suggestion: {
            id: "sg-replace",
            source_scene_ids: ["s1"],
            proposed_action: "replace",
            suggestion_kind: "replacement",
            proposed_scene: { draft_scenes: [] },
          },
          selector: 'input[name="review-suggestion"]',
          buttonText: "处理所选审查",
          nextTitle: "Scene 替换审查",
        },
      ]

      for (const item of cases) {
        document.body.innerHTML = `
          <div id="modal-overlay" class="hidden">
            <div id="modal-content">
              <h2 id="modal-title"></h2>
              <div id="modal-body"></div>
              <div id="modal-footer"></div>
            </div>
          </div>
        `
        sceneWorkbenchView._fusionSuggestions = [item.suggestion]
        sceneWorkbenchView._showFusionSuggestions()
        document.querySelector(item.selector).checked = true
        const action = Array.from(document.querySelectorAll("#modal-footer button"))
          .find((button) => button.textContent === item.buttonText)
        action.click()

        await vi.waitFor(() => expect(document.getElementById("modal-title").textContent).toBe(item.nextTitle))
        expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
      }
    } finally {
      Object.assign(globalThis, previousModalGlobals)
    }
  })

  it("dismisses at most the service batch limit at a time", async () => {
    showModal.mockReset()
    showModal.mockImplementation(() => {})
    api.outline.dismissFusionSuggestions.mockResolvedValue({ dismissed: 100 })
    vi.spyOn(sceneWorkbenchView, "_refreshWorkbenchInPlace").mockResolvedValue()
    sceneWorkbenchView._fusionSuggestions = Array.from({ length: 101 }, (_, index) => ({
      id: `suggestion-${index + 1}`,
      suggestion_kind: "fusion",
    }))

    sceneWorkbenchView._dismissAllFusionSuggestions()
    const html = modalHtmlFromCall(showModal.mock.calls[0])
    expect(html).toContain("本次先忽略 100 条")
    await showModal.mock.calls[0][2][1].handler()

    expect(api.outline.dismissFusionSuggestions).toHaveBeenCalledWith("p1", {
      suggestion_ids: Array.from({ length: 100 }, (_, index) => `suggestion-${index + 1}`),
      confirmed: true,
    })
  })

  it("opens replacement suggestions in a dedicated comparison flow", async () => {
    showModal.mockReset()
    showModal.mockImplementation(() => {})
    sceneWorkbenchView._workbench = workbenchPayload
    sceneWorkbenchView._fusionSuggestions = [{
      id: "sg-replace",
      source_scene_ids: ["s1"],
      chapter_span: [1, 2],
      proposed_action: "replace",
      suggestion_kind: "replacement",
      proposed_scene: {
        draft_scenes: [{
          title: "新版潜入",
          goal: "新版目标",
          chapter_ids: ["1", "2"],
        }],
        overlap_evidence: [{ chapter_index: 1, mode: "conservative_chapter" }],
      },
    }]

    sceneWorkbenchView._showFusionSuggestions()
    document.body.innerHTML = modalHtmlFromCall(showModal.mock.calls[0])
    document.querySelector('input[name="review-suggestion"]').checked = true
    const result = await showModal.mock.calls[0][2]
      .find((button) => button.text === "处理所选审查").handler()

    expect(showModal.mock.calls[1][0]).toBe("Scene 替换审查")
    const html = modalHtmlFromCall(showModal.mock.calls[1])
    const buttonTexts = showModal.mock.calls[1][2].map((button) => button.text)
    expect(html).toContain("受保护的原 Scene")
    expect(html).toContain("新版潜入")
    expect(buttonTexts).toContain("采用新 Scene，旧 Scene 移入历史")
    expect(buttonTexts).toContain("编辑后采用，旧 Scene 移入历史")
    expect(api.outline.previewSceneFusion).not.toHaveBeenCalled()
    expect(result).toBe(false)
  })

  it("applies a replacement only after explicit confirmation", async () => {
    autoConfirm()
    const refresh = vi.spyOn(sceneWorkbenchView, "_refreshWorkbenchInPlace")
      .mockResolvedValue()
    const suggestion = { id: "sg-replace" }

    const applied = await sceneWorkbenchView._applyReplacementSuggestion(
      suggestion,
      false,
    )

    expect(applied).toBe(true)
    expect(api.outline.applySceneReplacement).toHaveBeenCalledWith("p1", {
      suggestion_id: "sg-replace",
      decision: "replace",
      confirmed: true,
    })
    expect(confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("原 Scene 将移入历史"),
      expect.any(Function),
      "确认采用并移入历史",
    )
    expect(refresh).toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(
      "新 Scene 已采用，旧 Scene 已移入历史；建议按需重跑：world_objects、plot_structure",
      "success",
    )
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
