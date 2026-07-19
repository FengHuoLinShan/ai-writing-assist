import { beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { filterInboxItems, inboxSourceLabel, inboxTimeLabel, loadMapProps, mapSceneLabel, mapSourceText, readRecentMap, saveRecentMap } from "../../../vue/views/map/mapModel.js"

describe("mapModel", () => {
  beforeEach(() => {
    localStorage.clear()
    window.location.hash = "#workbench/p1/map?map_id=m1&scene_id=s1&mode=live"
    resetBridgeOverrides()
  })

  it("loads all catalog pages and freezes every request to the active project", async () => {
    const listMaps = vi.fn(async ({ novel_id, status, skip }) => ({
      items: status === "active" && skip === 0 ? Array.from({ length: 500 }, (_, index) => ({ id: `m${index}` })) : status === "active" ? [{ id: "m-last" }] : [],
    }))
    const listEntities = vi.fn(async ({ novel_id }) => ({ items: [{ id: "l1", name: "北港", novel_id }] }))
    const listInbox = vi.fn(async (projectId, params) => ({ items: [{ id: "o1" }], total: 1, has_more: false, projectId, params }))
    setBridgeOverrides({
      state: { currentProjectId: "p1" },
      router: { getCurrentQuery: () => new URLSearchParams("map_id=m1&mode=live") },
      api: { world: { listMaps, listEntities, listProjectMapObservationInbox: listInbox } },
    })

    const props = await loadMapProps()

    expect(props.route).toMatchObject({ projectId: "p1", mapId: "m1", sceneId: "s1", mode: "live" })
    expect(props.maps).toHaveLength(501)
    expect(listMaps.mock.calls.every(([params]) => params.novel_id === "p1")).toBe(true)
    expect(listEntities).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p1", entity_type: "location" }))
    expect(listInbox).toHaveBeenCalledWith("p1", expect.objectContaining({ skip: 0, limit: 20 }))
  })

  it("keeps recent-map and inbox filters project scoped", () => {
    saveRecentMap("p1", { id: "m1", name: "<script>alert(1)</script>" })
    saveRecentMap("p2", { id: "m2", name: "东海" })
    expect(readRecentMap("p1")).toMatchObject({ mapId: "m1" })
    expect(readRecentMap("p2")).toMatchObject({ mapId: "m2" })
    expect(filterInboxItems([
      { id: "a", source: "manual", confidence: 0.9, eligibility: { can_confirm: true } },
      { id: "b", source: "deep_import", confidence: 0.2, eligibility: { can_confirm: false } },
    ], { source: "manual", confidence: "high", eligibility: "ready" })).toEqual([expect.objectContaining({ id: "a" })])
  })

  it("将内部来源和零基 Scene 编号转为作者可读文案", () => {
    expect(inboxSourceLabel({ source: "map_enrichment_typed_map_proposal" })).toBe("地图事实补充")
    expect(mapSourceText("deep_import_delta_event · 路线")).toBe("深度导入 · 路线")
    expect(mapSceneLabel(0)).toBe("Scene 1")
    expect(inboxTimeLabel({ scene_index: 1, scene_sequence: 0 })).toBe("Scene 2 · 片段 1")
  })
})
