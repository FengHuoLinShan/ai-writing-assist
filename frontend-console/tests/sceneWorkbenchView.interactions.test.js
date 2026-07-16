import { beforeEach, describe, expect, it, vi } from "vitest"

import sceneWorkbenchView from "../views/sceneWorkbenchView.js"
import {
  persistActiveWorkflow,
  recoverActiveWorkflows,
} from "../shared/workflowProgress.js"
import {
  autoConfirm,
  captureModalHandler,
  modalHtmlFromCall,
  resetState,
  resetTestEnvironment,
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
  resetTestEnvironment({ currentProjectId: "p1", currentView: "scene", currentSubView: "s1" })
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

describe("sceneWorkbenchView — rendering filtering and interactions", () => {
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

})
