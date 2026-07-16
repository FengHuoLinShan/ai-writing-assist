import { beforeEach, describe, expect, it } from "vitest"

import { MapEditingSession } from "../views/mapEditingSession.js"

function createState() {
  return {
    editorLayer: "none",
    editorHistory: {},
    editorRedo: {},
    pendingTerrainChanges: {},
    pendingBindings: {},
    pendingLocationLayouts: {},
    pendingTerrainOverlay: null,
    pendingTerrainLayerDeletes: [],
    pendingMarkerChanges: {},
    pendingLayerTree: null,
    layerTreeBaselineStale: false,
    pendingTerritoryChanges: { add: {}, remove: {} },
    pendingPathChanges: {},
    pendingPathLayerChanges: {},
    selectedTerrainLayerId: null,
    selectedPathLayerId: null,
    selectedPathId: null,
  }
}

describe("MapEditingSession", () => {
  let state
  let session

  beforeEach(() => {
    state = createState()
    session = new MapEditingSession(state)
    session.syncBaseline("map-1", 7)
  })

  it("freezes apply revision, commands, and layer scope until commit", () => {
    state.editorLayer = "marker"
    state.pendingMarkerChanges.m1 = {
      operation: "update",
      id: "m1",
      data: { label: "提交标签" },
    }
    state.pendingTerrainChanges["1,1"] = {
      hex_q: 1,
      hex_r: 1,
      terrain_type: "forest",
    }
    const commands = [{
      type: "marker_update",
      ref: { id: "m1" },
      data: { label: "提交标签" },
    }]

    const { attempt } = session.beginApply(commands, { onlyLayer: true })
    commands[0].data.label = "请求后修改"
    state.editorLayer = "baseTerrain"

    expect(session.requestFor(attempt)).toEqual({
      expected_revision: 7,
      commands: [{
        type: "marker_update",
        ref: { id: "m1" },
        data: { label: "提交标签" },
      }],
    })
    expect(session.commitApply(attempt, { editor_revision: 8 })).toMatchObject({
      committed: true,
      clearedLayers: ["marker"],
      preservedLayers: [],
    })
    expect(state.pendingMarkerChanges).toEqual({})
    expect(state.pendingTerrainChanges["1,1"].terrain_type).toBe("forest")
    expect(session.baselineRevision).toBe(8)
    expect(session.isApplying()).toBe(false)
  })

  it("preserves same-layer edits created while an apply is in flight", () => {
    state.editorLayer = "marker"
    state.pendingMarkerChanges.m1 = {
      operation: "update",
      id: "m1",
      data: { label: "已提交版本" },
    }
    const { attempt } = session.beginApply([{
      type: "marker_update",
      ref: { id: "m1" },
      data: { label: "已提交版本" },
    }], { onlyLayer: true })

    state.pendingMarkerChanges.m1.data.label = "请求期间的新版本"
    session.recordCommand("marker", { kind: "marker", after: { label: "请求期间的新版本" } })
    const transition = session.commitApply(attempt, { editor_revision: 8 })

    expect(transition.preservedLayers).toEqual(["marker"])
    expect(state.pendingMarkerChanges.m1.data.label).toBe("请求期间的新版本")
    expect(state.editorHistory.marker).toHaveLength(1)
  })

  it("rejects a second apply until the active attempt reaches a terminal state", () => {
    const first = session.beginApply([{ type: "path_archive", ref: { id: "p1" } }])

    expect(session.isApplying()).toBe(true)
    expect(session.beginApply([{ type: "path_archive", ref: { id: "p2" } }])).toEqual({
      validationError: "地图编辑正在应用，请等待当前请求完成",
      attempt: null,
    })

    session.cancelApply(first.attempt)
    expect(session.isApplying()).toBe(false)
    expect(session.beginApply([{ type: "path_archive", ref: { id: "p2" } }]).attempt)
      .toBeTruthy()
    session.resetBaseline()
    expect(session.isApplying()).toBe(false)
  })

  it("keeps drafts on CAS conflict and advances the retry baseline", () => {
    state.editorLayer = "path"
    state.pendingPathChanges.clientPath = { operation: "create" }
    state.pendingLayerTree = [{ id: "path-root" }]
    const { attempt } = session.beginApply([{
      type: "path_create",
      client_id: "clientPath",
      data: { nodes: [{ q: 0, r: 0 }, { q: 1, r: 1 }] },
    }], { onlyLayer: true })

    expect(session.markConflict(attempt, 9)).toBe(true)
    expect(session.isApplying()).toBe(false)
    expect(state.pendingPathChanges.clientPath.operation).toBe("create")
    expect(state.layerTreeBaselineStale).toBe(true)

    const retry = session.beginApply([{ type: "path_archive", ref: { id: "p1" } }])
    expect(session.requestFor(retry.attempt).expected_revision).toBe(9)
  })

  it("reconciles temporary selections and preserves per-layer history", () => {
    state.selectedTerrainLayerId = "terrain-client"
    state.selectedPathLayerId = "layer-client"
    state.selectedPathId = "path-client"
    session.recordCommand("path", { kind: "draft", before: null, after: { paths: {} } })
    const { attempt } = session.beginApply([{ type: "path_archive", ref: { id: "p1" } }])

    session.commitApply(attempt, {
      editor_revision: 8,
      client_id_map: {
        "terrain-client": "terrain-real",
        "layer-client": "layer-real",
        "path-client": "path-real",
      },
    })

    expect(state.selectedTerrainLayerId).toBe("terrain-real")
    expect(state.selectedPathLayerId).toBe("layer-real")
    expect(state.selectedPathId).toBe("path-real")
    expect(state.editorHistory).toEqual({})
  })

  it("snapshots all editing drafts across a remote baseline reload", () => {
    state.editorLayer = "location"
    state.pendingBindings.a = { location_entity_id: "loc-1", hex_q: 2, hex_r: 3 }
    state.editorHistory.location = [{ kind: "location" }]
    const snapshot = session.snapshotForReload()

    session.discardDrafts()
    session.syncBaseline("map-1", 10)
    session.restoreAfterReload(snapshot)

    expect(state.pendingBindings.a.location_entity_id).toBe("loc-1")
    expect(state.editorHistory.location).toEqual([{ kind: "location" }])
    expect(session.baselineRevision).toBe(10)
  })
})
