/**
 * 地图视图测试 — PRD docs/PRD-动态地图功能.md
 *
 * 覆盖：
 * - mapHexRenderer 几何算法（hexToPixel/pixelToHex 往返、邻居、floodFill、hexRound）
 * - mapState 状态机（stage/consume/undo、reset）
 * - mapView 列表渲染（空列表、有地图列表、XSS 转义）
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { autoConfirm, createCanvasMock, renderHtml, resetTestEnvironment } from "./helpers.js"
import {
  hexToPixel,
  pixelToHex,
  hexRound,
  getNeighbors,
  floodFillTerrain,
  TERRAIN_COLORS,
  TERRAIN_OPTIONS,
  hexCorners,
  drawHexCell,
  drawTerrain,
  drawBindings,
  drawPendingTerrain,
  drawPendingBindings,
  drawHoverHighlight,
  drawCandidateBindings,
  drawCandidateMarkers,
  drawContextHighlights,
  drawMarkers,
  drawTerritories,
  hashColor,
} from "../views/mapHexRenderer.js"
import {
  mapState,
  resetMapState,
  stageTerrainChange,
  consumePendingChanges,
  popUndo,
  stageBindingChange,
  consumePendingBindings,
  setHoveredHex,
  clearHoveredHex,
  setSelectedHex,
  clearSelectedHex,
  startDragDraw,
  endDragDraw,
  recordDragHex,
  setCurrentScene,
} from "../views/mapState.js"
import mapView from "../views/mapView.js"
import renderEditPanel, { updatePendingCount, updateBindingPendingCount, toggleToolSections } from "../views/mapEditPanel.js"

async function importFreshMapView() {
  vi.resetModules()
  return (await import("../views/mapView.js")).default
}

function interceptLeafletResourceAppend() {
  const originalAppendChild = document.head.appendChild
  const originalGetElementById = document.getElementById
  const appended = []

  document.head.appendChild = vi.fn((node) => {
    if (node?.id === "leaflet-css-dynamic" || node?.id === "leaflet-js-dynamic") {
      node.remove = vi.fn(() => {
        node.dataset.removed = "true"
      })
      appended.push(node)
      return node
    }
    return originalAppendChild.call(document.head, node)
  })
  document.getElementById = vi.fn((id) => {
    const intercepted = appended.find((node) => node.id === id && node.dataset.removed !== "true")
    return intercepted || originalGetElementById.call(document, id)
  })

  return {
    appended,
    restore() {
      document.head.appendChild = originalAppendChild
      document.getElementById = originalGetElementById
    },
  }
}

beforeEach(() => {
  // 防御：单文件运行时 setup.js 可能未在同一 worker 执行，兜底初始化全局
  if (!globalThis.state) {
    globalThis.state = { currentProjectId: null, currentSubView: null }
  }
  resetTestEnvironment()
  resetMapState()
  mapView._maps = []
  mapView._mapsLoadError = null
  mapView._layerTree = null
  mapView._renderSubsetCache.clear()
  mapView._terrainOverviewCache.clear()
  mapView._renderMetrics = null
  mapView._dragLocationId = null
  mapView._dragMarkerId = null
  mapView._suppressNextCanvasClick = false
  mapView._lifecycleEpoch = 0
  mapView._mountContext = {}
  mapView._setEditorApplyBusy(false)
  document.getElementById("leaflet-css-dynamic")?.remove()
  document.getElementById("leaflet-js-dynamic")?.remove()
  delete window.L
})

// ============================================================
// 六边形几何
// ============================================================

describe("mapState P1 状态", () => {
  it("setCurrentScene 设置 scene id", () => {
    setCurrentScene("scene-123")
    expect(mapState.currentSceneId).toBe("scene-123")
  })

  it("setCurrentScene null 清除", () => {
    setCurrentScene("scene-123")
    setCurrentScene(null)
    expect(mapState.currentSceneId).toBeNull()
  })

  it("sceneList 和 currentScene 初始为空", () => {
    expect(mapState.sceneList).toEqual([])
    expect(mapState.currentScene).toBeNull()
  })

  it("marker 相关状态初始值", () => {
    expect(mapState.selectedMarkerType).toBe("character")
    expect(mapState.selectedMarkerEntityId).toBeNull()
    expect(mapState.selectedMarkerLabel).toBe("")
  })
})

describe("mapView Scene 时间轴", () => {
  it("_renderSceneBar 无 scene 数据时显示提示", () => {
    mapState.sceneList = []
    const html = mapView._renderSceneBar()
    expect(html).toContain("暂无 Scene 数据")
  })

  it("_renderSceneBar 有 scene 列表时显示导航", () => {
    mapState.sceneList = [
      { id: "s1", index: 1, title: "开端" },
      { id: "s2", index: 2, title: "发展" },
    ]
    mapState.currentSceneId = "s1"
    const html = mapView._renderSceneBar()
    expect(html).toContain("开端")
    expect(html).toContain("Scene 2")
    expect(html).toContain("map-scene-prev")
    expect(html).toContain("map-scene-next")
    expect(html).toContain("map-scene-clear")
  })

  it("在 workspace 回调确认前不提前改变当前 Scene", async () => {
    mapState.currentSceneId = "s1"
    const onSceneChange = vi.fn(() => false)
    mapView._mountContext = { onSceneChange }

    await expect(mapView._notifySceneChanged("s2")).resolves.toBe(false)

    expect(onSceneChange).toHaveBeenCalledWith("s2")
    expect(mapState.currentSceneId).toBe("s1")
  })

  it("无 workspace 回调时先提交 Scene 再刷新投影", async () => {
    mapState.currentSceneId = "s1"
    mapView._mountContext = {}
    const reload = vi.spyOn(mapView, "_reloadWithScene").mockResolvedValue(true)

    await mapView._notifySceneChanged("s2")

    expect(mapState.currentSceneId).toBe("s2")
    expect(reload).toHaveBeenCalledTimes(1)
    reload.mockRestore()
  })
})

describe("mapView marker 提示", () => {
  it.each([
    {
      name: "对 marker 返回标记信息",
      state: {
        map: { hex_size: 30, grid_width: 5, grid_height: 5 },
        tiles: [{ hex_q: 1, hex_r: 1, terrain_type: "grassland" }],
        location_bindings: [],
        markers: [{ hex_q: 1, hex_r: 1, marker_type: "character", label: "张三", visible: true }],
      },
      q: 1,
      r: 1,
      contain: ["张三", "人物"],
    },
    {
      name: "marker 优先级高于纯地形",
      state: {
        map: { hex_size: 30, grid_width: 5, grid_height: 5 },
        tiles: [{ hex_q: 2, hex_r: 2, terrain_type: "mountain" }],
        location_bindings: [],
        markers: [{ hex_q: 2, hex_r: 2, marker_type: "event", label: "决战", visible: true }],
      },
      q: 2,
      r: 2,
      contain: ["决战", "事件"],
    },
  ])("_buildTooltipContent $name", ({ state, q, r, contain }) => {
    mapView._state = state
    mapView._locations = []
    const html = mapView._buildTooltipContent(q, r)
    for (const text of contain) {
      expect(html).toContain(text)
    }
  })

  it("_buildTooltipContent 使用 marker 索引避免 hover 热路径数组扫描", () => {
    mapState.currentSceneId = "scene-1"
    const markers = [
      { hex_q: 1, hex_r: 1, marker_type: "character", label: "张三", visible: true },
      { hex_q: 2, hex_r: 2, marker_type: "event", label: "会战", visible: true, start_scene_id: "scene-1" },
    ]
    mapView._state = {
      map: { hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [{ hex_q: 1, hex_r: 1, terrain_type: "grassland" }],
      location_bindings: [],
      markers,
    }
    mapView._locations = []
    mapView._rebuildIndexes()

    markers.find = () => {
      throw new Error("marker find should not run during tooltip rendering")
    }
    markers.filter = () => {
      throw new Error("marker filter should not run during tooltip rendering")
    }

    const html = mapView._buildTooltipContent(1, 1)

    expect(html).toContain("张三")
    expect(html).toContain("会战")
  })
})

describe("mapView marker 编辑历史", () => {
  it("创建标记可以撤销并重做", async () => {
    globalThis.state.currentProjectId = "p1"
    mapState.mode = "edit"
    mapState.editorLayer = "marker"
    mapState.selectedMarkerEntityId = "entity-1"
    mapState.selectedMarkerType = "character"
    mapView._state = {
      map: { id: "m1", grid_width: 10, grid_height: 10 },
      markers: [],
      location_bindings: [],
      tiles: [],
    }
    await mapView._handleMarkerClick(2, 3)
    const draftId = mapView._state.markers[0].id
    expect(draftId).toMatch(/^[0-9a-f-]{36}$/)
    expect(mapState.pendingMarkerChanges[draftId]).toMatchObject({
      operation: "create",
      client_id: draftId,
    })
    expect(api.world.createMapMarker).not.toHaveBeenCalled()

    await mapView._undo()
    expect(mapView._state.markers).toEqual([])
    expect(api.world.deleteMapMarker).not.toHaveBeenCalled()

    await mapView._redo()
    expect(mapView._state.markers.map((marker) => marker.id)).toEqual([draftId])
    expect(mapState.pendingMarkerChanges[draftId].operation).toBe("create")
  })

  it("拖动后重建命中索引并抑制随后的 click", async () => {
    globalThis.state.currentProjectId = "p1"
    mapState.mode = "edit"
    mapState.editorLayer = "marker"
    const marker = {
      id: "marker-1",
      entity_id: "entity-1",
      marker_type: "character",
      hex_q: 2,
      hex_r: 2,
      visible: true,
    }
    mapView._state = {
      map: { id: "m1", grid_width: 10, grid_height: 10 },
      markers: [marker],
      location_bindings: [],
      tiles: [],
    }
    mapView._rebuildIndexes()
    mapView._dragMarkerId = marker.id
    mapView._pointerStartSnapshot = { ...marker }
    mapView._dragMoved = true
    marker.hex_q = 4
    marker.hex_r = 5
    api.world.updateMapMarker.mockResolvedValue({ ...marker })

    await mapView._handleCanvasMouseUp({ pointerId: 1 })

    expect(mapView._markerAt(2, 2)).toBeNull()
    expect(mapView._markerAt(4, 5)).toBe(marker)
    const create = vi.spyOn(mapView, "_handleMarkerClick")
    mapView._canvas = {}
    vi.spyOn(mapView, "_eventToHex").mockReturnValue([4, 5])
    mapView._handleCanvasClick({})
    expect(create).not.toHaveBeenCalled()
    create.mockRestore()
    mapView._eventToHex.mockRestore()
  })
})

describe("mapView 原子保存与渲染裁剪", () => {
  it("递归图层面板展示继承值并折叠子树", () => {
    mapState.collapsedLayerNodeIds.add("group")
    const html = renderEditPanel({
      locations: [],
      allEntities: [],
      scenes: [],
      terrainLayers: [],
      territoryTools: "",
      layerTree: [
        {
          id: "group",
          node_type: "group",
          layer_key: null,
          name: "自定义组",
          depth: 1,
          visible: true,
          locked: true,
          opacity: 0.5,
          effective_visible: true,
          effective_locked: true,
          effective_opacity: 0.5,
          effective_min_zoom: -1,
          effective_max_zoom: 2,
        },
        {
          id: "child",
          parent_id: "group",
          node_type: "leaf",
          name: "子图层",
          depth: 2,
          visible: true,
          locked: false,
          opacity: 1,
        },
      ],
    })

    expect(html).toContain("自定义组")
    expect(html).toContain("继承锁定 · 50% · -1~2")
    expect(html).not.toContain("子图层")
  })

  it("工具区明确展示当前图层的继承锁定状态", () => {
    mapState.editorLayer = "marker"
    mapState.selectedMarkerType = "character"
    const html = renderEditPanel({
      locations: [],
      allEntities: [],
      scenes: [],
      terrainLayers: [],
      territoryTools: "",
      layerTree: [{
        id: "marker-character",
        node_type: "leaf",
        layer_key: "marker.character",
        name: "人物",
        visible: true,
        locked: false,
        effective_locked: true,
        opacity: 1,
      }],
    })

    expect(html).toContain('data-editor-locked="true"')
    expect(html).toContain("画布工具已停用")
  })

  it("标记对象只展示当前标记类型并保留已选对象", () => {
    mapState.editorLayer = "marker"
    mapState.selectedMarkerType = "event"
    mapState.selectedMarkerEntityId = "event-1"
    const html = renderEditPanel({
      locations: [],
      allEntities: [
        { id: "character-1", name: "克莱恩", entity_type: "character" },
        { id: "event-1", name: "塔罗聚会", entity_type: "event" },
        { id: "item-1", name: "安提哥努斯笔记", entity_type: "item" },
      ],
      scenes: [],
      terrainLayers: [],
      territoryTools: "",
      layerTree: [],
    })

    expect(html).toContain('<option value="event" selected>事件</option>')
    expect(html).toContain('<option value="event-1" selected>塔罗聚会</option>')
    expect(html).not.toContain("克莱恩")
    expect(html).not.toContain("安提哥努斯笔记")
  })

  it("地点编辑器保留当前选择并明确显示锁定状态", () => {
    mapState.editorLayer = "location"
    mapState.selectedLocationEntityId = "loc-2"

    const html = renderEditPanel({
      locations: [
        { id: "loc-1", name: "廷根市" },
        { id: "loc-2", name: "黑荆棘安保公司" },
      ],
      locationLayouts: [
        { location_entity_id: "loc-2", locked: true },
      ],
      layerTree: [],
    })

    expect(html).toContain('<option value="loc-2" selected>黑荆棘安保公司</option>')
    expect(html).toContain("黑荆棘安保公司 · 已锁定")
    expect(html).toContain(">解锁地点</button>")
  })

  it("线路编辑器展示名称、端点偏离和单一领地工具语义", () => {
    mapState.editorLayer = "path"
    mapState.selectedPathId = "path-1"
    mapState.selectedPathLayerId = "layer-1"
    mapView._allEntities = [{ id: "org-1", name: "值夜者", entity_type: "organization" }]

    const html = renderEditPanel({
      locations: [{ id: "loc-1", name: "黑荆棘安保公司" }],
      layerTree: [],
      pathLayers: [{ id: "layer-1", category: "transport", name: "道路" }],
      pathProfiles: { street: { category: "transport", label: "街道" } },
      paths: [{
        id: "path-1",
        name: "佐特兰街",
        path_layer_id: "layer-1",
        path_type: "street",
        nodes: [{ q: 1, r: 1 }, { q: 3, r: 3 }],
        start_location_entity_id: "loc-1",
        start_endpoint_status: {
          name: "黑荆棘安保公司", drifted: true, unresolved: false, distance: 1.25,
        },
      }],
      territoryTools: mapView._renderTerritoryTools(),
    })

    expect(html).toContain('id="map-path-name"')
    expect(html).toContain('value="佐特兰街"')
    expect(html).toContain("1 条线路的地点端点已偏离")
    expect(html).toContain("重新吸附全部偏离端点")
    expect(html).not.toContain('data-action="map-territory-paint"')
  })

  it("切换标记类型时清空旧选择并刷新候选对象", () => {
    mapState.editorLayer = "marker"
    mapState.selectedMarkerType = "character"
    mapState.selectedMarkerEntityId = "character-1"
    mapView._allEntities = [
      { id: "character-1", name: "克莱恩", entity_type: "character" },
      { id: "event-1", name: "塔罗聚会", entity_type: "event" },
    ]
    document.body.innerHTML = `<main id="workspace-content">${renderEditPanel({
      allEntities: mapView._allEntities,
      layerTree: [],
    })}</main>`
    mapView._bindMapEvents()
    const typeSelect = document.getElementById("map-marker-type")
    typeSelect.value = "event"

    typeSelect.dispatchEvent(new Event("change"))

    expect(mapState.selectedMarkerType).toBe("event")
    expect(mapState.selectedMarkerEntityId).toBeNull()
    expect(document.getElementById("map-marker-entity").textContent).toContain("塔罗聚会")
    expect(document.getElementById("map-marker-entity").textContent).not.toContain("克莱恩")
    mapView.unmount()
  })

  it("revision 冲突时保留当前图层草稿", async () => {
    state.currentProjectId = "p1"
    mapView._state = {
      map: { id: "m1", editor_revision: 3, grid_width: 10, grid_height: 10 },
      tiles: [],
      location_bindings: [],
      markers: [],
      territories: [],
      terrain_layers: [],
      terrain_regions: [],
      terrain_patches: [],
    }
    mapState.editorLayer = "baseTerrain"
    mapState.pendingTerrainChanges = {
      "1,1": { hex_q: 1, hex_r: 1, terrain_type: "water" },
    }
    const error = new Error("conflict")
    error.status = 409
    error.body = {
      error: "map_editor_revision_conflict",
      context: { current_revision: 4 },
    }
    api.world.applyMapEditor
      .mockRejectedValueOnce(error)
      .mockResolvedValueOnce({ editor_revision: 5, command_results: [], client_id_map: {} })
    api.world.getMapState.mockResolvedValue({
      ...mapView._state,
      map: { ...mapView._state.map, editor_revision: 4 },
      markers: [{ id: "remote-marker", label: "其他会话的新标签" }],
    })
    api.world.getMapLayerTree.mockResolvedValue({ editor_revision: 4, nodes: [] })

    expect(await mapView._applyAllChanges({ onlyLayer: true })).toBe(false)

    expect(mapState.pendingTerrainChanges["1,1"].terrain_type).toBe("water")
    expect(toast).toHaveBeenCalledWith(
      expect.stringContaining("草稿已保留"),
      "warning",
    )
    expect(mapView._state.map.editor_revision).toBe(4)
    expect(mapView._state.markers[0].label).toBe("其他会话的新标签")

    expect(await mapView._applyAllChanges({ onlyLayer: true })).toBe(true)
    expect(api.world.applyMapEditor.mock.calls[1][1].expected_revision).toBe(4)
  })

  it("filters unchanged terrain and territory commands before apply", () => {
    mapView._state = {
      map: { id: "m1", editor_revision: 1 },
      tiles: [{ hex_q: 1, hex_r: 1, terrain_type: "water", elevation: 0 }],
      territories: [{ id: "t1", faction_entity_id: "f1", hex_q: 2, hex_r: 2, style_override: {} }],
    }
    mapView._tileByHex = new Map()
    mapState.pendingTerrainChanges = {
      "1,1": { hex_q: 1, hex_r: 1, terrain_type: "water", elevation: null },
    }
    mapState.pendingTerritoryChanges = {
      add: { duplicate: { faction_entity_id: "f1", hex_q: 2, hex_r: 2, style_override: {} } },
      remove: {},
    }

    expect(mapView._buildEditorCommands()).toEqual([])
  })

  it("filters unchanged location layout and binding drafts before apply", () => {
    const layout = {
      location_entity_id: "loc-1",
      center_hex_q: 1,
      center_hex_r: 2,
      occupy_radius: 1,
      locked: false,
      layout_source: "user_drag",
      layout_version: 1,
      sync_geo_setting: false,
      meta: {},
    }
    mapView._state = {
      map: { id: "m1", editor_revision: 1 },
      location_layouts: [layout],
      location_bindings: [{
        id: "binding-1",
        location_entity_id: "loc-1",
        hex_q: 1,
        hex_r: 2,
        is_center: true,
        label_override: null,
        style_override: {},
      }],
    }
    mapState.pendingLocationLayouts = { "loc-1": { ...layout } }
    mapState.pendingBindings = {
      same: {
        location_entity_id: "loc-1",
        hex_q: 1,
        hex_r: 2,
        is_center: true,
      },
    }

    expect(mapView._buildEditorCommands()).toEqual([])
  })

  it("rejects oversized unified editor drafts before API submission", async () => {
    mapView._state = { map: { id: "m1", editor_revision: 1 }, tiles: [], territories: [] }
    mapView._tileByHex = new Map()
    mapState.editorLayer = "baseTerrain"
    mapState.pendingTerrainChanges = Object.fromEntries(
      Array.from({ length: 10001 }, (_, index) => [
        `${index},0`,
        { hex_q: index, hex_r: 0, terrain_type: "water" },
      ]),
    )

    expect(await mapView._applyAllChanges({ onlyLayer: true })).toBe(false)
    expect(api.world.applyMapEditor).not.toHaveBeenCalled()
    expect(Object.keys(mapState.pendingTerrainChanges)).toHaveLength(10001)

    mapState.editorLayer = "territory"
    mapState.pendingTerritoryChanges = {
      add: Object.fromEntries(Array.from({ length: 5001 }, (_, index) => [
        `draft:f1:${index},0`,
        { faction_entity_id: "f1", hex_q: index, hex_r: 0 },
      ])),
      remove: {},
    }
    expect(await mapView._applyAllChanges({ onlyLayer: true })).toBe(false)
    expect(api.world.applyMapEditor).not.toHaveBeenCalled()
    expect(Object.keys(mapState.pendingTerritoryChanges.add)).toHaveLength(5001)

    mapState.editorLayer = "location"
    mapView._state = {
      map: { id: "m1", editor_revision: 1 },
      location_layouts: [],
      location_bindings: Array.from({ length: 5000 }, (_, index) => ({
        id: `binding-${index}`,
        location_entity_id: "loc-1",
        hex_q: index,
        hex_r: 0,
        is_center: index === 0,
        style_override: {},
      })),
    }
    mapState.pendingBindings = {
      extra: {
        location_entity_id: "loc-1",
        hex_q: 5000,
        hex_r: 0,
        is_center: false,
      },
    }
    expect(await mapView._applyAllChanges({ onlyLayer: true })).toBe(false)
    expect(api.world.applyMapEditor).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(
      "单个地点单次最多绑定 5000 个地图格，请减少选中范围",
      "error",
    )

    mapState.editorLayer = "marker"
    mapState.pendingMarkerChanges = Object.fromEntries(
      Array.from({ length: 201 }, (_, index) => [
        `marker-${index}`,
        { operation: "update", id: `marker-${index}`, data: { label: `标记 ${index}` } },
      ]),
    )
    expect(await mapView._applyAllChanges({ onlyLayer: true })).toBe(false)
    expect(api.world.applyMapEditor).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(
      "单次最多应用 200 个编辑命令，请减少本次变更",
      "error",
    )
  })

  it("applying the current layer preserves another layer tree draft", async () => {
    state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1", editor_revision: 1 }, tiles: [], territories: [] }
    mapState.editorLayer = "marker"
    mapState.pendingMarkerChanges = {
      marker1: { operation: "update", id: "marker1", data: { label: "新标签" } },
    }
    mapState.pendingLayerTree = [{ id: "tree1", node_type: "leaf", name: "地形", visible: true }]
    mapState.pendingLayerTreeLayer = "baseTerrain"
    api.world.applyMapEditor.mockResolvedValue({ editor_revision: 2 })
    vi.spyOn(mapView, "_reloadMapStatePreservingSession").mockResolvedValue()
    vi.spyOn(mapView, "_loadLayerTree").mockResolvedValue()
    vi.spyOn(mapView, "_redraw").mockImplementation(() => {})

    expect(await mapView._applyAllChanges({ onlyLayer: true })).toBe(true)
    expect(api.world.applyMapEditor.mock.calls[0][1].commands).toEqual([
      { type: "marker_update", ref: { id: "marker1" }, data: { label: "新标签" } },
    ])
    expect(mapState.pendingLayerTree).toEqual([
      { id: "tree1", node_type: "leaf", name: "地形", visible: true },
    ])
    expect(mapState.pendingLayerTreeLayer).toBe("baseTerrain")
  })

  it("触控 Pointer 拖动地点时暂停并恢复 Leaflet 平移", async () => {
    const disable = vi.fn()
    const enable = vi.fn()
    const setPointerCapture = vi.fn()
    const releasePointerCapture = vi.fn()
    mapView._state = {
      map: { id: "m1", grid_width: 10, grid_height: 10 },
      location_layouts: [{
        location_entity_id: "loc-1",
        center_hex_q: 1,
        center_hex_r: 1,
        locked: false,
      }],
      location_bindings: [],
      markers: [],
    }
    mapView._canvas = { setPointerCapture, releasePointerCapture }
    mapView._leaflet = { dragging: { disable, enable } }
    mapState.mode = "edit"
    mapState.editorLayer = "location"
    mapState.activeTool = "locationMove"
    const eventToHex = vi.spyOn(mapView, "_eventToHex")
      .mockReturnValueOnce([1, 1])
      .mockReturnValueOnce([2, 2])
    const preventDefault = vi.fn()

    mapView._handleCanvasMouseDown({
      pointerId: 7,
      pointerType: "touch",
      type: "pointerdown",
      preventDefault,
    })
    mapView._handleCanvasMouseMove({ pointerId: 7, pointerType: "touch" })
    await mapView._handleCanvasMouseUp({ pointerId: 7, type: "pointerup" })

    expect(setPointerCapture).toHaveBeenCalledWith(7)
    expect(disable).toHaveBeenCalledTimes(1)
    expect(mapState.pendingLocationLayouts["loc-1"]).toMatchObject({
      center_hex_q: 2,
      center_hex_r: 2,
    })
    expect(releasePointerCapture).toHaveBeenCalledWith(7)
    expect(enable).toHaveBeenCalledTimes(1)
    expect(preventDefault).toHaveBeenCalledTimes(1)
    eventToHex.mockRestore()
  })

  it("编辑态仍复用按 revision 缓存的视口绘制队列", () => {
    mapView._renderSubsetCache.clear()
    mapView._canvas = { width: 300, height: 240 }
    mapView._state = {
      map: { id: "m1", editor_revision: 7 },
      tiles: [
        { id: "near", hex_q: 1, hex_r: 1, terrain_type: "grassland" },
        { id: "far", hex_q: 199, hex_r: 199, terrain_type: "water" },
      ],
      location_bindings: [],
      markers: [],
      territories: [],
      terrain_layers: [],
      terrain_regions: [],
      terrain_patches: [],
      candidate_location_bindings: [],
      candidate_markers: [],
      candidate_territories: [],
    }
    mapState.pendingTerrainChanges = {
      "2,2": { hex_q: 2, hex_r: 2, terrain_type: "forest" },
    }

    const first = mapView._visibleRenderSubset(30, { x: 0, y: 0 }, 1, 0)
    const cached = mapView._visibleRenderSubset(30, { x: 0, y: 0 }, 1, 0)

    expect(first.tiles.map((tile) => tile.id)).toEqual(["near"])
    expect(cached).toBe(first)
    expect(mapView._renderMetrics).toMatchObject({
      editor_revision: 7,
      total_hex_items: 2,
      queued_hex_items: 1,
    })

    mapView._state.map.editor_revision = 8
    const invalidated = mapView._visibleRenderSubset(30, { x: 0, y: 0 }, 1, 0)
    expect(invalidated).not.toBe(first)

    mapView._layerTree = {
      nodes: [{
        id: "base",
        layer_key: "baseTerrain",
        visible: false,
        locked: false,
        opacity: 1,
      }],
    }
    mapView._state.map.editor_revision = 9
    const hidden = mapView._visibleRenderSubset(30, { x: 0, y: 0 }, 1, 0)
    expect(hidden.tiles).toEqual([])
    expect(mapView._renderMetrics.queued_hex_items).toBe(0)
    expect(mapView._renderMetrics.culled_hex_items).toBe(2)
  })

  it("大地图缩放总览复用低分辨率地形快照", () => {
    const originalGetContext = HTMLCanvasElement.prototype.getContext
    const context = createCanvasMock({
      captureAlpha: false,
      methods: ["fillRect"],
    })
    HTMLCanvasElement.prototype.getContext = vi.fn(() => context)
    mapView._state = {
      map: {
        id: "large-map",
        editor_revision: 3,
        grid_width: 40,
        grid_height: 25,
      },
      tiles: Array.from({ length: 1000 }, (_, index) => ({
        hex_q: index % 40,
        hex_r: Math.floor(index / 40),
        terrain_type: index % 2 ? "grassland" : "water",
      })),
    }

    try {
      const first = mapView._terrainOverviewRaster(30)
      const cached = mapView._terrainOverviewRaster(30)

      expect(first).not.toBeNull()
      expect(cached).toBe(first)
      expect(first.canvas.width).toBeGreaterThan(0)
      expect(first.canvas.height).toBeGreaterThan(0)
      expect(context.fillRect).toHaveBeenCalledTimes(1000)

      mapView._state.map.editor_revision = 4
      expect(mapView._terrainOverviewRaster(30)).not.toBe(first)
      expect(context.fillRect).toHaveBeenCalledTimes(2000)
    } finally {
      HTMLCanvasElement.prototype.getContext = originalGetContext
    }
  })

  it("场景动态数据更新会失效视口缓存并重建 marker 索引", () => {
    mapView._state = {
      map: { id: "m1", editor_revision: 1 },
      markers: [{ id: "old", hex_q: 1, hex_r: 1, visible: true }],
      territories: [],
      location_bindings: [],
    }
    mapView._rebuildIndexes()
    mapView._renderSubsetCache.set("stale", { markers: [{ id: "old" }] })

    mapView._applyDynamicState({
      markers: [{ id: "new", hex_q: 2, hex_r: 2, visible: true }],
      territories: [],
      candidate_location_bindings: [],
      candidate_markers: [],
      candidate_territories: [],
    })

    expect(mapView._renderSubsetCache.size).toBe(0)
    expect(mapView._markerAt(1, 1)).toBeNull()
    expect(mapView._markerAt(2, 2)).toMatchObject({ id: "new" })
  })

  it("类型化选择优先区分 marker、territory、terrain 与 location", () => {
    mapView._state = {
      map: { id: "m1" },
      tiles: [{ id: "tile", hex_q: 1, hex_r: 1, terrain_type: "city" }],
      location_bindings: [{ id: "binding", location_entity_id: "loc", hex_q: 1, hex_r: 1 }],
      markers: [{ id: "marker", entity_id: "char", marker_type: "character", hex_q: 1, hex_r: 1, visible: true }],
      territories: [{ id: "territory", faction_entity_id: "org", hex_q: 2, hex_r: 2 }],
      terrain_layers: [{ id: "layer", visible: true, opacity: 1 }],
      terrain_regions: [],
      terrain_patches: [{ id: "patch", layer_id: "layer", hex_q: 3, hex_r: 3 }],
    }
    mapView._rebuildIndexes()

    expect(mapView._typedSelectionAt(1, 1).kind).toBe("marker")
    expect(mapView._typedSelectionAt(2, 2).kind).toBe("territory")
    expect(mapView._typedSelectionAt(3, 3).kind).toBe("terrain")
  })
})


describe("mapView P2 势力范围", () => {
  const orgEntities = [{ id: "o1", entity_type: "organization", name: "青龙会" }]

  it.each([
    { name: "无组织时显示提示", entities: [], contain: ["暂无组织实体"] },
    { name: "有组织时显示选择器", entities: orgEntities, contain: ["青龙会", "map-territory-faction"] },
  ])("_renderTerritoryTools $name", ({ entities, contain }) => {
    mapView._allEntities = entities
    const html = mapView._renderTerritoryTools()
    for (const text of contain) {
      expect(html).toContain(text)
    }
  })

  it.each([
    { name: "无组织时返回空", entities: [], expected: "" },
    { name: "有组织时显示标签", entities: orgEntities, contain: ["青龙会", "map-focus-toggle"] },
  ])("_renderFactionList $name", ({ entities, expected, contain }) => {
    mapView._allEntities = entities
    const html = mapView._renderFactionList()
    if (expected !== undefined) {
      expect(html).toBe(expected)
    }
    for (const text of contain || []) {
      expect(html).toContain(text)
    }
  })

  it("falls back when faction color is not a safe hex color", () => {
    mapView._allEntities = orgEntities
    mapState.factionColors.o1 = "red;background-image:url(https://example.test/x)"

    const html = mapView._renderFactionList()

    expect(html).not.toContain("background-image")
    expect(html).toContain("background:#99922")
    expect(html).toContain("border-color:#999")
  })

  it("聚焦模式切换", () => {
    mapView._toggleFocusMode("o1")
    expect(mapState.focusMode).toBe(true)
    expect(mapState.focusEntityId).toBe("o1")
    mapView._toggleFocusMode("o1")
    expect(mapState.focusMode).toBe(false)
  })

  it.each([
    { name: "非聚焦模式返回 1.0", focusMode: false, related: [], q: 1, r: 1, expected: 1.0 },
    { name: "聚焦模式关联格返回 1.0", focusMode: true, related: ["1,1"], q: 1, r: 1, expected: 1.0 },
    { name: "聚焦模式非关联格返回 0.3", focusMode: true, related: ["1,1"], q: 2, r: 2, expected: 0.3 },
  ])("_getHexOpacity $name", ({ focusMode, related, q, r, expected }) => {
    mapState.focusMode = focusMode
    mapState.focusRelatedHexes = new Set(related)
    expect(mapView._getHexOpacity(q, r)).toBe(expected)
  })

  it("按一级地图工作台图层上下文过滤 marker", () => {
    mapView._mountContext = { layers: { markers: true, events: false, items: false } }
    mapView._state = {
      markers: [
        { id: "mk1", marker_type: "character", visible: true },
        { id: "mk2", marker_type: "event", visible: true },
        { id: "mk3", marker_type: "item", visible: true },
        { id: "mk4", marker_type: "character", visible: false },
      ],
    }

    expect(mapView._filteredMarkers().map((m) => m.id)).toEqual(["mk1"])
  })

  it("presentation 更新保持当前 viewport lifecycle owner", () => {
    const owner = { viewMode: "live", focusEntityId: "old" }
    mapView._mountContext = owner

    expect(mapView.setPresentationContext({
      viewMode: "lens",
      lowMotion: true,
      focusEntityId: "new",
    })).toBe(true)

    expect(mapView._mountContext).toBe(owner)
    expect(owner).toMatchObject({
      viewMode: "lens",
      lowMotion: true,
      focusEntityId: "new",
    })
  })

  it("待确认图层默认关闭，打开后才返回 candidate marker", () => {
    mapView._mountContext = { layers: {} }
    mapView._state = {
      candidate_markers: [
        { id: "candidate-1", marker_type: "character", visible: true },
      ],
    }

    expect(mapView._candidateMarkers()).toEqual([])

    mapView._mountContext = { layers: { candidate: true } }
    expect(mapView._candidateMarkers().map((m) => m.id)).toEqual(["candidate-1"])
  })

  it("Scene 高亮优先于 focusEntityId", () => {
    mapView._mountContext = { sceneId: "s1", focusEntityId: "loc1" }
    mapView._state = {
      location_bindings: [{ location_entity_id: "loc1", hex_q: 3, hex_r: 3 }],
      markers: [
        { entity_id: "c1", marker_type: "character", start_scene_id: "s1", hex_q: 1, hex_r: 1, visible: true },
      ],
      territories: [],
    }

    expect(mapView._contextHighlightHexes()).toEqual([
      { hex_q: 1, hex_r: 1, kind: "scene" },
    ])
  })

  it("Scene 高亮包含后端已过滤出的持续可见 marker", () => {
    mapView._mountContext = { sceneId: "s2" }
    mapView._state = {
      location_bindings: [{ location_entity_id: "loc1", hex_q: 2, hex_r: 2, is_center: true }],
      markers: [
        {
          entity_id: "c1",
          marker_type: "character",
          start_scene_id: "s1",
          start_scene_index: 1,
          end_scene_id: null,
          end_scene_index: null,
          hex_q: 2,
          hex_r: 2,
          visible: true,
        },
      ],
      territories: [],
    }

    expect(mapView._contextHighlightHexes()).toEqual([
      { hex_q: 2, hex_r: 2, kind: "primary_location" },
      { hex_q: 2, hex_r: 2, kind: "scene" },
    ])
  })

  it("无 Scene 时使用 focusEntityId 高亮地点", () => {
    mapView._mountContext = { focusEntityId: "loc1" }
    mapView._state = {
      location_bindings: [{ location_entity_id: "loc1", hex_q: 3, hex_r: 3 }],
      markers: [],
      territories: [],
    }

    expect(mapView._contextHighlightHexes()).toEqual([
      { hex_q: 3, hex_r: 3, kind: "focus" },
    ])
  })
})

describe("mapHexRenderer P2 drawTerritories", () => {
  it.each([
    { name: "空数组不绘制", territories: [], colorMap: {}, expectBeginPath: false },
    { name: "绘制势力范围", territories: [{ faction_id: "f1", hexes: [{ hex_q: 1, hex_r: 1 }] }], colorMap: { f1: "#FF0000" }, expectBeginPath: true, fillStyleContains: "FF0000" },
    { name: "绘制后端 flat 领地格", territories: [{ faction_entity_id: "f2", hex_q: 2, hex_r: 3 }], colorMap: { f2: "#00FF00" }, expectBeginPath: true, fillStyleContains: "00FF00" },
  ])("drawTerritories $name", ({ territories, colorMap, expectBeginPath, fillStyleContains }) => {
    const ctx = createCanvasMock()
    drawTerritories(ctx, territories, 30, 0, 0, colorMap)
    if (expectBeginPath) {
      expect(ctx.beginPath).toHaveBeenCalled()
    } else {
      expect(ctx.beginPath).not.toHaveBeenCalled()
    }
    if (fillStyleContains) {
      // createCanvasMock 默认不记录 fillStyle，用 recordCalls 记录
      expect(ctx.fillStyle).toContain(fillStyleContains)
    }
  })

  it("hashColor 生成确定性颜色", () => {
    const c1 = hashColor("org-1")
    const c2 = hashColor("org-1")
    expect(c1).toBe(c2)
    expect(c1).toMatch(/^#[0-9A-Fa-f]{6}$/)
  })
})

describe("mapHexRenderer candidate and context layers", () => {
  it("drawCandidateMarkers uses weakened style and pending label", () => {
    const ctx = createCanvasMock({ recordCalls: true })

    drawCandidateMarkers(ctx, [
      { hex_q: 1, hex_r: 1, marker_type: "character", label: "候选人物", visible: true },
    ], 30, 0, 0)

    expect(ctx._calls.arc).toBe(1)
    expect(ctx._calls.fillText.some(([text]) => text === "待处理")).toBe(true)
  })

  it("drawCandidateBindings uses dashed pending outline", () => {
    const ctx = createCanvasMock({ recordCalls: true })

    drawCandidateBindings(ctx, [
      { hex_q: 1, hex_r: 1, is_center: true },
    ], 30, 0, 0)

    expect(ctx._calls.beginPath).toBeGreaterThan(0)
    expect(ctx._calls.setLineDash).toContainEqual([5, 4])
    expect(ctx._calls.fillText.some(([text]) => text === "待")).toBe(true)
  })

  it("drawContextHighlights draws one outline per highlight", () => {
    const ctx = createCanvasMock({ recordCalls: true })

    drawContextHighlights(ctx, [
      { hex_q: 1, hex_r: 1, kind: "scene" },
      { hex_q: 2, hex_r: 1, kind: "focus" },
    ], 30, 0, 0)

    expect(ctx._calls.beginPath).toBe(2)
  })
})

describe("mapView 批量地图操作", () => {
  it("批量归档地图调用归档 API", async () => {
    state.currentProjectId = "p1"
    mapView._maps = [{ id: "m1", name: "主地图" }, { id: "m2", name: "地下城" }]
    mapView._bulkSelections = { "map-list": new Set(["m1", "m2"]) }
    api.world.archiveMap.mockResolvedValue({})
    const loadMaps = vi.spyOn(mapView, "_loadMaps").mockResolvedValue()
    const render = vi.spyOn(mapView, "_render").mockImplementation(() => {})
    autoConfirm()

    await mapView._runMapBulkAction("delete-maps")

    await vi.waitFor(() => {
      expect(api.world.archiveMap).toHaveBeenCalledWith("m1", "p1")
      expect(api.world.archiveMap).toHaveBeenCalledWith("m2", "p1")
      expect(toast).toHaveBeenCalledWith(expect.stringContaining("成功 2 / 2"), "success")
    })
    loadMaps.mockRestore()
    render.mockRestore()
  })
})

describe("图层会话与连续线路纵切", () => {
  it("应用当前内容层不携带图层树草稿", () => {
    mapView._state = {
      map: { id: "m1", editor_revision: 1 },
      tiles: [], location_layouts: [], location_bindings: [], territories: [], markers: [],
    }
    mapState.editorLayer = "baseTerrain"
    mapState.pendingTerrainChanges = {
      "1,1": { hex_q: 1, hex_r: 1, terrain_type: "forest" },
    }
    mapState.pendingLayerTree = [{
      id: "base", node_type: "leaf", layer_key: "baseTerrain", name: "底图",
      visible: true, locked: false, opacity: 1, sort_order: 0,
    }]

    expect(mapView._buildEditorCommands({ onlyLayer: true }).map((item) => item.type))
      .toEqual(["base_terrain_replace"])
    expect(mapView._buildEditorCommands({ onlyLayerTree: true }).map((item) => item.type))
      .toEqual(["layer_tree_replace"])
  })

  it("路径图层与手绘路径在同一 batch 通过 client ref 引用", () => {
    mapView._state = { map: { id: "m1", editor_revision: 1 }, territories: [], markers: [] }
    mapState.mode = "edit"
    mapState.editorLayer = "path"
    mapState.pendingPathLayerChanges = {
      layerClient: {
        operation: "create",
        client_id: "layerClient",
        leaf_client_id: "leafClient",
        data: { display_name: "水系", category: "water", meta: {} },
      },
    }
    mapState.pendingPathChanges = {
      pathClient: {
        operation: "create",
        client_id: "pathClient",
        data: {
          path_layer_id: "layerClient",
          name: "长河",
          path_type: "river",
          nodes: [
            { q: 1, r: 1, width_scale: 1, tension: 0.5 },
            { q: 2, r: 2, width_scale: 1, tension: 0.5 },
          ],
        },
      },
    }

    const commands = mapView._buildEditorCommands({ onlyLayer: true })
    expect(commands.map((item) => item.type)).toEqual(["path_layer_create", "path_create"])
    expect(commands[1].data.layer_ref).toEqual({ client_id: "layerClient" })
    expect(commands[1].data.nodes[0]).not.toHaveProperty("sort_order")
  })

  it("手绘新路径后立即刷新列表选中态", () => {
    document.body.innerHTML = `<div id="map-root"></div>`
    mapView._mountRootId = "map-root"
    mapView._state = {
      map: { id: "m1", grid_width: 8, grid_height: 8 },
      breadcrumbs: [],
      terrain_layers: [],
      territories: [],
      markers: [],
    }
    mapView._layerTree = { nodes: [] }
    mapView._pathState = {
      path_layers: [{ id: "roads", name: "道路", category: "transport", status: "active" }],
      paths: [],
      nodes: [],
    }
    mapState.mode = "edit"
    mapState.editorLayer = "path"
    mapState.selectedPathLayerId = "roads"
    mapState.selectedPathType = "major_road"
    mapView._pathPointerSamples = [{ q: 1, r: 1 }, { q: 2, r: 2 }]
    mapView._pointerStartSnapshot = mapView._snapshotActiveDraft()
    mapView._dragMoved = true
    mapView._canvas = { releasePointerCapture: vi.fn() }
    mapView._leaflet = {
      dragging: { enable: vi.fn() },
      off: vi.fn(),
      remove: vi.fn(),
    }
    const defer = vi.spyOn(mapView, "_defer").mockImplementation(() => null)

    mapView._handlePathPointerUp({ type: "pointerup", pointerId: 7 })

    const activePath = document.querySelector(".map-path-list-row.active")
    expect(activePath).not.toBeNull()
    expect(activePath.dataset.id).toBe(mapState.selectedPathId)
    expect(activePath.textContent).toContain("主干道")
    defer.mockRestore()
  })

  it("保存全部时将新路径图层 leaf 合并进完整图层树", () => {
    mapView._state = { map: { id: "m1", editor_revision: 1 }, territories: [], markers: [] }
    mapState.pendingLayerTree = [
      {
        id: "path-root", node_type: "group", layer_key: "path", name: "线路",
        visible: true, locked: false, opacity: 1, sort_order: 0, selection_mode: "floor",
      },
      {
        id: "old-leaf", parent_id: "path-root", node_type: "leaf",
        path_layer_id: "old-layer", name: "旧线路", visible: true,
        locked: false, opacity: 1, sort_order: 0, floor_level: -1,
      },
      {
        id: "kept-leaf", parent_id: "path-root", node_type: "leaf",
        path_layer_id: "kept-layer", name: "保留线路", visible: true,
        locked: false, opacity: 1, sort_order: 1, floor_level: 0,
      },
    ]
    mapState.pendingPathLayerChanges = {
      newLayer: {
        operation: "create",
        client_id: "newLayer",
        leaf_client_id: "newLeaf",
        data: { display_name: "新水系", category: "water", meta: {} },
      },
      oldLayer: { operation: "delete", id: "old-layer" },
    }

    const commands = mapView._buildEditorCommands()
    const tree = commands.find((command) => command.type === "layer_tree_replace")

    expect(commands.map((command) => command.type)).toEqual([
      "path_layer_create", "path_layer_delete", "layer_tree_replace",
    ])
    expect(tree.nodes).not.toContainEqual(expect.objectContaining({ path_layer_id: "old-layer" }))
    expect(tree.nodes).toContainEqual(expect.objectContaining({
      client_id: "newLeaf",
      parent_id: "path-root",
      path_layer_client_id: "newLayer",
      name: "新水系",
      floor_level: 1,
    }))
  })

  it("应用成功后将新路径选中项从 client id 替换为正式 id", async () => {
    state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1", editor_revision: 1 }, territories: [], markers: [] }
    mapState.mode = "edit"
    mapState.editorLayer = "path"
    mapState.selectedPathLayerId = "layerClient"
    mapState.selectedPathId = "pathClient"
    mapState.pendingPathLayerChanges = {
      layerClient: {
        operation: "create",
        client_id: "layerClient",
        leaf_client_id: "leafClient",
        data: { display_name: "道路", category: "transport", meta: {} },
      },
    }
    mapState.pendingPathChanges = {
      pathClient: {
        operation: "create",
        client_id: "pathClient",
        data: {
          path_layer_id: "layerClient",
          name: "大路",
          path_type: "major_road",
          nodes: [{ q: 0, r: 0 }, { q: 1, r: 1 }],
        },
      },
    }
    api.world.applyMapEditor.mockResolvedValue({
      editor_revision: 2,
      client_id_map: { layerClient: "layer-real", pathClient: "path-real" },
    })
    const reloadSpy = vi.spyOn(mapView, "_reloadMapStatePreservingSession").mockResolvedValue()
    const treeSpy = vi.spyOn(mapView, "_loadLayerTree").mockResolvedValue()
    const pathsSpy = vi.spyOn(mapView, "_loadPaths").mockResolvedValue()
    const redrawSpy = vi.spyOn(mapView, "_redraw").mockImplementation(() => {})
    const rerenderSpy = vi.spyOn(mapView, "_rerenderEditor").mockImplementation(() => {})

    expect(await mapView._applyAllChanges({ onlyLayer: true })).toBe(true)
    expect(mapState.selectedPathLayerId).toBe("layer-real")
    expect(mapState.selectedPathId).toBe("path-real")
    expect(rerenderSpy).toHaveBeenCalled()
    reloadSpy.mockRestore()
    treeSpy.mockRestore()
    pathsSpy.mockRestore()
    redrawSpy.mockRestore()
    rerenderSpy.mockRestore()
  })

  it("并行加载路径安全兼容嵌入 nodes 响应", async () => {
    state.currentProjectId = "n1"
    mapView._state = { map: { id: "m1" } }
    api.world.getMapPaths.mockResolvedValue({
      editor_revision: 3,
      layers: [{ id: "l1", name: "道路", category: "transport" }],
      paths: [{ id: "p1", path_layer_id: "l1", nodes: [{ id: "n1", q: 1, r: 1 }] }],
    })

    await mapView._loadPaths()

    expect(api.world.getMapPaths).toHaveBeenCalledWith("m1", "n1", "all")
    expect(mapView._pathState.nodes).toHaveLength(1)
    expect(mapState.selectedPathLayerId).toBe("l1")
  })

  it("线路端点可绑定地点并重新吸附到当前锚点", () => {
    mapView._state = {
      map: { id: "m1" },
      location_layouts: [{
        location_entity_id: "loc-1",
        center_hex_q: 4,
        center_hex_r: 5,
      }],
      location_bindings: [],
    }
    mapView._pathState = {
      path_layers: [{ id: "l1", category: "transport" }],
      paths: [{
        id: "p1",
        path_layer_id: "l1",
        path_type: "street",
        nodes: [{ q: 1, r: 1 }, { q: 2, r: 2 }],
      }],
      nodes: [],
    }
    mapState.editorLayer = "path"
    mapState.selectedPathId = "p1"
    mapState.selectedPathLayerId = "l1"

    expect(mapView._stageSelectedPathEndpoint("start", "loc-1", true)).toBe(true)

    expect(mapState.pendingPathChanges.p1).toMatchObject({
      operation: "update",
      data: {
        start_location_entity_id: "loc-1",
        nodes: [{ q: 4, r: 5 }, { q: 2, r: 2 }],
      },
    })
    expect(mapState.editorHistory.path).toHaveLength(1)
  })

  it("线路可就地重命名并保留在同一编辑历史中", () => {
    mapView._state = { map: { id: "m1" }, location_layouts: [], location_bindings: [] }
    mapView._pathState = {
      path_layers: [{ id: "l1", category: "transport" }],
      paths: [{
        id: "p1", name: "主干道 1", path_layer_id: "l1", path_type: "street",
        nodes: [{ q: 1, r: 1 }, { q: 2, r: 2 }],
      }],
      nodes: [],
    }
    mapState.editorLayer = "path"
    mapState.selectedPathId = "p1"
    mapState.selectedPathLayerId = "l1"
    const rerender = vi.spyOn(mapView, "_rerenderEditor").mockImplementation(() => {})

    expect(mapView._stageSelectedPathName("  佐特兰街  ")).toBe(true)

    expect(mapState.pendingPathChanges.p1).toMatchObject({
      operation: "update",
      data: { name: "佐特兰街" },
    })
    expect(mapState.editorHistory.path).toHaveLength(1)
    rerender.mockRestore()
  })

  it("线路端点偏离后可一次重新吸附全部已布置地点", () => {
    mapView._state = {
      map: { id: "m1" },
      location_layouts: [
        { location_entity_id: "start", center_hex_q: 4, center_hex_r: 5 },
        { location_entity_id: "end", center_hex_q: 8, center_hex_r: 9 },
      ],
      location_bindings: [],
    }
    mapView._pathState = {
      path_layers: [{ id: "l1", category: "transport" }],
      paths: [{
        id: "p1",
        path_layer_id: "l1",
        path_type: "street",
        start_location_entity_id: "start",
        end_location_entity_id: "end",
        nodes: [{ q: 1, r: 1 }, { q: 2, r: 2 }, { q: 3, r: 3 }],
      }],
      nodes: [],
    }
    mapState.editorLayer = "path"
    mapState.selectedPathId = "p1"
    mapState.selectedPathLayerId = "l1"
    const rerender = vi.spyOn(mapView, "_rerenderEditor").mockImplementation(() => {})

    expect(mapView._resnapPathEndpoints("p1")).toBe(true)

    expect(mapState.pendingPathChanges.p1.data.nodes).toMatchObject([
      { q: 4, r: 5 },
      { q: 2, r: 2 },
      { q: 8, r: 9 },
    ])
    expect(mapState.editorHistory.path).toHaveLength(1)
    rerender.mockRestore()
  })

  it("楼层会话选择直接影响 path leaf 有效可见性", () => {
    mapState.activeLayerChildIds = { floors: "f0" }
    mapView._layerTree = { nodes: [
      { id: "floors", node_type: "group", selection_mode: "floor", visible: true },
      { id: "f0", parent_id: "floors", node_type: "group", selection_mode: "normal", floor_level: 0, visible: true },
      { id: "f1", parent_id: "floors", node_type: "group", selection_mode: "normal", floor_level: 1, visible: true },
      { id: "p0", parent_id: "f0", node_type: "leaf", path_layer_id: "l0", visible: true },
      { id: "p1", parent_id: "f1", node_type: "leaf", path_layer_id: "l1", visible: true },
    ] }

    expect(mapView._effectiveLayerNode({ pathLayerId: "l0" }).visible).toBe(true)
    expect(mapView._effectiveLayerNode({ pathLayerId: "l1" })).toMatchObject({
      visible: false,
      sessionReason: "非当前楼层",
    })
  })

  it("详情与 typed selection 不会命中结构隐藏或 isolate 背景层", () => {
    mapView._state = {
      map: { id: "m1" },
      tiles: [{ id: "tile", hex_q: 0, hex_r: 0, terrain_type: "plain" }],
      location_bindings: [{ id: "binding", location_entity_id: "loc", hex_q: 1, hex_r: 0 }],
      territories: [{ id: "territory", faction_entity_id: "f1", hex_q: 2, hex_r: 0 }],
      terrain_layers: [{ id: "terrain-layer", visible: true }],
      terrain_patches: [{ id: "patch", layer_id: "terrain-layer", hex_q: 3, hex_r: 0 }],
      terrain_regions: [], markers: [],
    }
    mapView._mountContext = { layers: {} }
    mapView._layerTree = { nodes: [
      { id: "base", node_type: "leaf", layer_key: "baseTerrain", visible: true },
      { id: "location", node_type: "leaf", layer_key: "location", visible: false },
      { id: "territory", node_type: "leaf", layer_key: "territory", visible: false },
      { id: "overlay", node_type: "group", layer_key: "terrainOverlay", visible: true },
      { id: "patch-leaf", parent_id: "overlay", node_type: "leaf", terrain_layer_id: "terrain-layer", visible: false },
    ] }
    mapState.isolateLayerNodeId = "location"

    expect(mapView._effectiveLayerNode({ layerKey: "baseTerrain" })).toMatchObject({
      visible: true,
      interactiveVisible: false,
    })
    expect(mapView._typedSelectionAt(0, 0)).toBeNull()
    expect(mapView._typedSelectionAt(1, 0)).toBeNull()
    expect(mapView._typedSelectionAt(2, 0)).toBeNull()
    expect(mapView._typedSelectionAt(3, 0)).toBeNull()
    expect(mapView._renderDetailPanel(0, 0)).toContain("点击地图查看详情")
  })

  it("显式点击地点标签时地点详情优先于同格人物标记", () => {
    document.body.innerHTML = '<div id="map-detail-panel"></div>'
    mapView._state = {
      map: { id: "m1" },
      tiles: [],
      location_bindings: [{
        id: "binding-1",
        location_entity_id: "loc-1",
        hex_q: 4,
        hex_r: 8,
        is_center: true,
      }],
      markers: [{
        id: "marker-1",
        entity_id: "char-1",
        marker_type: "character",
        label: "克莱恩",
        hex_q: 4,
        hex_r: 8,
        visible: true,
      }],
      territories: [],
      terrain_layers: [],
      terrain_patches: [],
      terrain_regions: [],
    }
    mapView._locations = [{ id: "loc-1", name: "灰雾之上", summary: "非物理空间" }]
    mapView._maps = []
    mapView._rebuildIndexes()

    expect(mapView._onCenterClick("loc-1")).toBe(true)
    expect(document.getElementById("map-detail-panel").textContent).toContain("灰雾之上")
    expect(document.getElementById("map-detail-panel").textContent).not.toContain("克莱恩")
  })

  it("地点标记线路势力与 Scene 动态共享地图标签布局输入", () => {
    window.L = {
      latLng: (lat, lng) => ({ lat, lng }),
    }
    mapView._leaflet = {
      getZoom: () => 0,
      latLngToContainerPoint: ({ lat, lng }) => ({ x: lng, y: -lat }),
    }
    mapView._state = {
      map: { id: "m1", hex_size: 30 },
      location_bindings: [{
        location_entity_id: "loc-1", hex_q: 1, hex_r: 1, is_center: true,
      }],
      markers: [{
        id: "marker-1", entity_id: "char-1", marker_type: "character",
        label: "克莱恩", hex_q: 2, hex_r: 2, visible: true,
      }],
      territories: [{ faction_entity_id: "org-1", hex_q: 4, hex_r: 4 }],
    }
    mapView._locations = [{ id: "loc-1", name: "莫雷蒂家公寓" }]
    mapView._allEntities = [{ id: "org-1", name: "值夜者" }]
    mapView._pathState = {
      path_layers: [{ id: "layer-1", category: "transport" }],
      paths: [{
        id: "path-1", name: "佐特兰街", path_layer_id: "layer-1",
        path_type: "street", nodes: [{ q: 1, r: 3 }, { q: 3, r: 3 }],
      }],
      nodes: [],
    }
    mapView._timelineProjection = {
      stateItems: [{
        id: "fact-1", dynamic_type: "crisis", target_name: "神秘污染",
        spatial_anchor: { hex_q: 5, hex_r: 5 },
      }],
    }
    mapView._rebuildIndexes()

    const items = mapView._buildMapLabelItems()

    expect(new Set(items.map((item) => item.source_kind))).toEqual(new Set([
      "location", "marker", "path", "territory", "dynamic",
    ]))
    expect(items.find((item) => item.source_kind === "path")).toMatchObject({
      title: "佐特兰街", q: 2, r: 3,
    })
    expect(items.find((item) => item.source_kind === "dynamic")).toMatchObject({
      title: "神秘污染", priority: 96,
    })
  })

  it("归档不覆盖未保存线路编辑，再次点击取消已 staging 的归档", async () => {
    mapView._state = { map: { id: "m1" } }
    mapView._pathState = {
      path_layers: [{ id: "l1", category: "transport" }],
      paths: [{ id: "p1", path_layer_id: "l1", path_type: "street", status: "active" }],
      nodes: [],
    }
    mapState.editorLayer = "path"
    mapState.pendingPathChanges = {
      p1: { operation: "update", id: "p1", data: { name: "未保存新名" } },
    }

    await mapView._togglePathArchive("p1")

    expect(mapState.pendingPathChanges.p1).toMatchObject({ operation: "update" })
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("未保存编辑"), "warning")
    expect(api.world.getMapPathArchiveImpact).not.toHaveBeenCalled()

    mapState.pendingPathChanges.p1 = { operation: "archive", id: "p1" }
    vi.spyOn(mapView, "_rerenderEditor").mockImplementationOnce(() => {})
    await mapView._togglePathArchive("p1")
    expect(mapState.pendingPathChanges.p1).toBeUndefined()
    expect(api.world.getMapPathArchiveImpact).not.toHaveBeenCalled()
  })

  it("地图 action delegation 绑定在局部 map root，不会被工作台委派覆盖", async () => {
    document.body.innerHTML = `
      <div id="workspace-content">
        <div id="map-root"><button data-action="map-path-archive" data-id="p1">归档</button></div>
      </div>
    `
    mapView._mountRootId = "map-root"
    const archive = vi.spyOn(mapView, "_togglePathArchive").mockResolvedValue()

    mapView._bindMapEvents()
    document.querySelector("[data-action='map-path-archive']").click()
    await Promise.resolve()

    expect(document.getElementById("map-root").__delegation_click).toEqual(expect.any(Function))
    expect(archive).toHaveBeenCalledWith("p1")
    archive.mockRestore()
  })

  it("当 path-only 保存创建图层时将后端自动 leaf 合并回图层树草稿", () => {
    mapView._state = { map: { id: "m1" } }
    mapState.pendingLayerTree = [{
      id: "path-root", node_type: "group", layer_key: "path", name: "线路",
      visible: true, locked: false, opacity: 1, sort_order: 0,
    }]
    mapView._layerTree = { nodes: [
      mapState.pendingLayerTree[0],
      {
        id: "leaf-real", parent_id: "path-root", node_type: "leaf",
        path_layer_id: "layer-real", name: "水系", visible: true,
        locked: false, opacity: 1, sort_order: 0,
      },
    ] }

    mapView._reconcilePendingLayerTreeAfterPathLayerApply([{
      type: "path_layer_create",
      client_id: "layer-client",
      leaf_client_id: "leaf-client",
    }], {
      "layer-client": "layer-real",
      "leaf-client": "leaf-real",
    })

    expect(mapState.pendingLayerTree).toContainEqual(expect.objectContaining({
      id: "leaf-real",
      parent_id: "path-root",
      path_layer_id: "layer-real",
    }))
  })

  it("可从编辑面板 staging 删除空线路图层", () => {
    mapView._state = { map: { id: "m1" } }
    mapView._pathState = {
      path_layers: [{ id: "l1", name: "旧交通", category: "transport" }],
      paths: [], nodes: [],
    }
    mapView._layerTree = { nodes: [{
      id: "leaf", node_type: "leaf", path_layer_id: "l1", visible: true, locked: false,
    }] }
    mapState.editorLayer = "path"
    mapState.selectedPathLayerId = "l1"
    autoConfirm()
    vi.spyOn(mapView, "_rerenderEditor").mockImplementationOnce(() => {})

    mapView._deleteSelectedPathLayer()

    expect(mapState.pendingPathLayerChanges.l1).toEqual({ operation: "delete", id: "l1" })
    expect(mapView._buildEditorCommands({ onlyLayer: true })).toContainEqual({
      type: "path_layer_delete",
      ref: { id: "l1" },
    })
  })

  it("线路按图层树 DFS 顺序而非 path layer id 渲染", () => {
    mapView._layerTree = { nodes: [
      { id: "root", node_type: "group", layer_key: "path", sort_order: 0 },
      { id: "z-leaf", parent_id: "root", node_type: "leaf", path_layer_id: "z-layer", sort_order: 0 },
      { id: "a-leaf", parent_id: "root", node_type: "leaf", path_layer_id: "a-layer", sort_order: 1 },
    ] }
    mapView._pathState = {
      path_layers: [], nodes: [],
      paths: [
        { id: "a-path", path_layer_id: "a-layer", sort_order: 0 },
        { id: "z-path", path_layer_id: "z-layer", sort_order: 0 },
      ],
    }

    expect(mapView._effectivePaths().map((path) => path.id)).toEqual(["z-path", "a-path"])
  })

  it("聚焦 path 可由 path layer 反查 leaf 并激活对应楼层", () => {
    mapView._state = { map: { id: "m1", hex_size: 30 } }
    mapView._pathState = {
      path_layers: [{ id: "l1", category: "water" }],
      paths: [{ id: "p1", path_layer_id: "l1", path_type: "river", nodes: [{ q: 1, r: 1 }, { q: 2, r: 2 }] }],
      nodes: [],
    }
    mapView._layerTree = { nodes: [
      { id: "floors", node_type: "group", selection_mode: "floor", visible: true },
      { id: "f0", parent_id: "floors", node_type: "group", floor_level: 0, visible: true },
      { id: "f1", parent_id: "floors", node_type: "group", floor_level: 1, visible: true },
      { id: "path-leaf", parent_id: "f1", node_type: "leaf", path_layer_id: "l1", visible: true },
    ] }
    mapState.activeLayerChildIds = { floors: "f0" }

    expect(mapView.focusPath("p1")).toBe(true)

    expect(mapView._mountContext.focusLayerNodeId).toBe("path-leaf")
    expect(mapState.activeLayerChildIds.floors).toBe("f1")
    expect(mapState.selectedPathLayerId).toBe("l1")
    expect(mapState.selectedPathType).toBe("river")
  })

  it("清除路由 path 聚焦时可保留编辑器内的 path 选择", () => {
    mapView._mountContext = { focusPathId: "p1", focusLayerNodeId: "leaf-1" }
    mapState.selectedPathId = "p1"
    mapState.selectedPathNodeIndex = 2
    mapState.selectedMapObject = { kind: "path", id: "p1" }

    mapView.clearPathFocus({ preserveSelection: true })

    expect(mapView._mountContext.focusPathId).toBeNull()
    expect(mapView._mountContext.focusLayerNodeId).toBeNull()
    expect(mapState.selectedPathId).toBe("p1")
    expect(mapState.selectedPathNodeIndex).toBe(2)
    expect(mapState.selectedMapObject).toEqual({ kind: "path", id: "p1" })
  })

  it("根据已加载 path content_revision 判断事实快照是否过期", () => {
    mapView._pathState = {
      path_layers: [], nodes: [],
      paths: [{ id: "p1", content_revision: 4 }],
    }

    expect(mapView.pathRevisionMismatch({ path_id: "p1", path_revision: 3 })).toBe(true)
    expect(mapView.pathRevisionMismatch({ path_id: "p1", path_revision: 4 })).toBe(false)
  })

  it("pointercancel 回滚 path 节点草稿并恢复 Leaflet 平移", () => {
    mapView._state = { map: { id: "m1" } }
    mapState.editorLayer = "path"
    mapState.pendingPathChanges = {
      p1: { operation: "update", id: "p1", data: { nodes: [{ q: 1, r: 1 }, { q: 2, r: 2 }] } },
    }
    mapView._pointerStartSnapshot = mapView._snapshotActiveDraft()
    mapState.pendingPathChanges.p1.data.nodes[0] = { q: 9, r: 9 }
    mapView._dragPathNode = { pathId: "p1", index: 0 }
    mapView._canvas = { releasePointerCapture: vi.fn() }
    mapView._leaflet = { dragging: { enable: vi.fn() } }
    vi.spyOn(mapView, "_rerenderEditor").mockImplementationOnce(() => {})

    mapView._handlePathPointerUp({ type: "pointercancel", pointerId: 7 })

    expect(mapState.pendingPathChanges.p1.data.nodes[0]).toEqual({ q: 1, r: 1 })
    expect(mapState.editorHistory.path || []).toHaveLength(0)
    expect(mapView._canvas.releasePointerCapture).toHaveBeenCalledWith(7)
    expect(mapView._leaflet.dragging.enable).toHaveBeenCalled()
  })

  it("path pointerdown 统一 capture pointer 并暂停 Leaflet 平移", () => {
    mapView._state = { map: { id: "m1", grid_width: 8, grid_height: 8 } }
    mapState.editorLayer = "path"
    mapState.pathTool = "draw"
    mapState.selectedPathLayerId = "l1"
    mapView._canvas = { setPointerCapture: vi.fn() }
    mapView._leaflet = { dragging: { disable: vi.fn() } }
    vi.spyOn(mapView, "_eventToAxial").mockReturnValue([1, 1])
    const event = { pointerId: 9, preventDefault: vi.fn() }

    mapView._handlePathPointerDown(event)

    expect(mapView._canvas.setPointerCapture).toHaveBeenCalledWith(9)
    expect(mapView._leaflet.dragging.disable).toHaveBeenCalled()
    expect(event.preventDefault).toHaveBeenCalled()
  })

  it("选中既有 path 同步图层与类型，跨类别移动时清理无效 segment type", () => {
    mapView._state = { map: { id: "m1" } }
    mapView._pathState = {
      path_layers: [
        { id: "roads", category: "transport" },
        { id: "water", category: "water" },
      ],
      paths: [{
        id: "p1", path_layer_id: "roads", path_type: "street", status: "active",
        nodes: [{ q: 1, r: 1, segment_type: "street" }, { q: 2, r: 2 }],
      }],
      nodes: [],
    }
    mapState.editorLayer = "path"
    mapView._selectPath(mapView._pathState.paths[0])

    expect(mapState.selectedPathLayerId).toBe("roads")
    expect(mapState.selectedPathType).toBe("street")
    expect(mapView._stageSelectedPathClassification({ layerId: "water", pathType: "street" })).toBe(true)
    expect(mapState.pendingPathChanges.p1).toMatchObject({
      operation: "update",
      data: { path_layer_id: "water", path_type: "river" },
    })
    expect(mapState.pendingPathChanges.p1.data.nodes[0]).not.toHaveProperty("segment_type")
  })

  it("既有 path 移入当批新建图层时使用 client ref", () => {
    mapView._state = { map: { id: "m1" }, territories: [], markers: [] }
    mapState.editorLayer = "path"
    mapState.pendingPathLayerChanges = {
      newLayer: {
        operation: "create",
        client_id: "newLayer",
        leaf_client_id: "newLeaf",
        data: { display_name: "新水系", category: "water", meta: {} },
      },
    }
    mapState.pendingPathChanges = {
      p1: {
        operation: "update",
        id: "p1",
        data: { path_layer_id: "newLayer", path_type: "river" },
      },
    }

    const update = mapView._buildEditorCommands({ onlyLayer: true })
      .find((command) => command.type === "path_update")
    expect(update.data.layer_ref).toEqual({ client_id: "newLayer" })
  })
})
