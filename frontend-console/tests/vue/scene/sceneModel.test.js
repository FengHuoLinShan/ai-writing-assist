import { beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import {
  SCENE_FILTER_DEFAULTS,
  commitSceneRouteQuery,
  loadSceneWorkbenchProps,
  persistSceneSession,
  resetSceneSession,
  sceneSession,
  sceneWorkbenchParams,
} from "../../../vue/views/scene/sceneModel.js"

describe("sceneModel", () => {
  const state = {
    currentProjectId: "p1",
    currentView: "outline",
    currentSubView: "scenes",
  }
  const router = { getCurrentQuery: vi.fn(() => new URLSearchParams()) }
  const api = {
    outline: {
      getSceneWorkbench: vi.fn(),
      listFusionSuggestions: vi.fn(),
    },
  }

  beforeEach(() => {
    sessionStorage.clear()
    resetBridgeOverrides()
    resetSceneSession("p1")
    vi.clearAllMocks()
    router.getCurrentQuery.mockReturnValue(new URLSearchParams())
    api.outline.getSceneWorkbench.mockResolvedValue({
      items: [], total: 0, skip: 0, fusion_suggestions: { pending_count: 0 },
    })
    setBridgeOverrides({ state, router, api })
  })

  it("anchors only the unfiltered hot first page", () => {
    expect(sceneWorkbenchParams({
      filters: { ...SCENE_FILTER_DEFAULTS },
      viewMode: "hot",
    })).toEqual({ skip: 0, limit: 20, view_mode: "hot", anchor: "latest" })

    expect(sceneWorkbenchParams({
      filters: { ...SCENE_FILTER_DEFAULTS, q: "潜入" },
      viewMode: "hot",
    })).toEqual({ skip: 0, limit: 20, view_mode: "hot", q: "潜入" })
  })

  it("restores validated project filters from the current browser session", () => {
    sessionStorage.setItem("novel_scene_workbench_session:p2", JSON.stringify({
      filters: { ...SCENE_FILTER_DEFAULTS, segment: "current", skip: 20, limit: 999, phase1a_fallback: "yes" },
      filterDraft: { ...SCENE_FILTER_DEFAULTS, q: "尚未应用", skip: 20 },
      activeHealth: "missing_setup",
      advancedFiltersOpen: true,
    }))

    expect(sceneSession("p2")).toEqual({
      filters: { ...SCENE_FILTER_DEFAULTS, segment: "current", skip: 20 },
      filterDraft: { ...SCENE_FILTER_DEFAULTS, q: "尚未应用", skip: 20 },
      activeHealth: "missing_setup",
      advancedFiltersOpen: true,
    })
    persistSceneSession("p2", sceneSession("p2"))
    expect(JSON.parse(sessionStorage.getItem("novel_scene_workbench_session:p2"))).toEqual(sceneSession("p2"))
    resetSceneSession("p2")
    expect(sessionStorage.getItem("novel_scene_workbench_session:p2")).toBeNull()
  })

  it("prefetches the selected scene and all durable suggestion pages", async () => {
    router.getCurrentQuery.mockReturnValue(new URLSearchParams("mode=normal&scene_id=s25&suggestion_id=sg-50"))
    sceneSession("p1").filters = { ...SCENE_FILTER_DEFAULTS, skip: 20 }
    api.outline.getSceneWorkbench.mockResolvedValue({
      items: [{ scene: { id: "s25" } }],
      total: 51,
      skip: 20,
      fusion_suggestions: { pending_count: 51 },
    })
    api.outline.listFusionSuggestions
      .mockResolvedValueOnce({ items: Array.from({ length: 50 }, (_, index) => ({ id: `sg-${index}` })), total: 51 })
      .mockResolvedValueOnce({ items: [{ id: "sg-50" }], total: 51 })

    const props = await loadSceneWorkbenchProps("p1")

    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", "s25", {
      skip: 0,
      limit: 20,
      view_mode: "normal",
    })
    expect(api.outline.listFusionSuggestions).toHaveBeenNthCalledWith(1, "p1", { skip: 0, limit: 50 })
    expect(api.outline.listFusionSuggestions).toHaveBeenNthCalledWith(2, "p1", { skip: 50, limit: 50 })
    expect(props.selectedSceneId).toBe("s25")
    expect(props.focusedSuggestionId).toBe("sg-50")
    expect(props.fusionSuggestions).toHaveLength(51)
    expect(props.sceneFilters.skip).toBe(20)
  })

  it("404 恢复时清除 scene_id 并经 commitCurrentQuery 就地更新 query", async () => {
    router.getCurrentQuery.mockReturnValue(new URLSearchParams("scene_id=missing"))
    api.outline.getSceneWorkbench
      .mockRejectedValueOnce(Object.assign(new Error("Scene not found"), { status: 404, detail: "Scene not found" }))
      .mockResolvedValueOnce({ items: [], total: 0, skip: 0, fusion_suggestions: { pending_count: 0 } })
    const commitCurrentQuery = vi.fn(() => true)
    setBridgeOverrides({ state, router: { ...router, commitCurrentQuery }, api })

    const props = await loadSceneWorkbenchProps("p1")

    expect(props.selectedSceneId).toBeNull()
    expect(commitCurrentQuery).toHaveBeenCalledWith(expect.any(URLSearchParams), "replace")
    expect(commitCurrentQuery.mock.calls[0][0].get("scene_id")).toBeNull()
  })

  it("路由未挂载时 commitSceneRouteQuery 直接重写 history 兜底", () => {
    window.history.replaceState({}, "", "#workbench/p1/outline/scenes?scene_id=s1")
    commitSceneRouteQuery("p1", new URLSearchParams("mode=hot"))
    expect(window.location.hash).toBe("#workbench/p1/outline/scenes?mode=hot")
    commitSceneRouteQuery("p1", new URLSearchParams(), "push")
    expect(window.location.hash).toBe("#workbench/p1/outline/scenes")
  })
})
