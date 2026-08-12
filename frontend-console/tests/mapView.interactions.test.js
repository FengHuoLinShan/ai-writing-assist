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
import { createRetryableLeafletLoader } from "../views/leafletLoader.js"
import renderEditPanel, { updatePendingCount, updateBindingPendingCount, toggleToolSections } from "../views/mapEditPanel.js"

async function importFreshMapView() {
  vi.resetModules()
  return (await import("../views/mapView.js")).default
}

function createLeafletHarness(container, { fittedZoom = -5 } = {}) {
  const leafletMap = {
    getBoundsZoom: vi.fn(() => fittedZoom),
    setMinZoom: vi.fn(),
    fitBounds: vi.fn(),
    setView: vi.fn(),
    on: vi.fn(),
    off: vi.fn(function () { return this }),
    getZoom: vi.fn(() => 0),
    latLngToContainerPoint: vi.fn(() => ({ x: 24, y: 36 })),
    eachLayer: vi.fn(),
    removeLayer: vi.fn(),
    getContainer: vi.fn(() => container),
    remove: vi.fn(),
  }
  const leafletApi = {
    CRS: { Simple: {} },
    map: vi.fn(() => leafletMap),
    latLngBounds: vi.fn((bounds) => bounds),
    latLng: vi.fn((lat, lng) => ({ lat, lng })),
  }
  return { leafletApi, leafletMap }
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
  mapView._renderMetrics = null
  mapView._dragLocationId = null
  mapView._dragMarkerId = null
  mapView._suppressNextCanvasClick = false
  mapView._lifecycleEpoch = 0
  mapView._mountContext = {}
  mapView._leafletApi = null
  mapView._setEditorApplyBusy(false)
})

describe("mapView 页内重绘", () => {
  it("保留已平移缩放的地图视口", async () => {
    vi.useFakeTimers()
    document.body.append(renderHtml('<div id="map-root"></div>'))
    const center = { lat: -128, lng: 256 }
    mapView._mountRootId = "map-root"
    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      breadcrumbs: [],
      tiles: [],
      location_bindings: [],
      markers: [],
      territories: [],
      terrain_layers: [],
    }
    mapView._leaflet = {
      getCenter: vi.fn(() => center),
      getZoom: vi.fn(() => 2),
      off: vi.fn(),
      remove: vi.fn(),
    }
    const container = document.createElement("div")
    const { leafletApi, leafletMap } = createLeafletHarness(container)
    const originalGetContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = vi.fn(() => createCanvasMock({
      methods: ["setTransform", "clearRect", "translate", "scale"],
    }))
    const initLeaflet = mapView._initLeaflet.bind(mapView)
    const init = vi.spyOn(mapView, "_initLeaflet").mockImplementation(
      (_loadLeaflet, viewport) => initLeaflet(async () => leafletApi, viewport),
    )

    try {
      mapView._rerenderEditor()
      await vi.runAllTimersAsync()
      await vi.waitFor(() => {
        expect(leafletMap.setView).toHaveBeenCalledWith(center, 2, { animate: false })
      })
    } finally {
      init.mockRestore()
      mapView._teardownInteractiveSurface()
      mapView._state = null
      HTMLCanvasElement.prototype.getContext = originalGetContext
      vi.useRealTimers()
    }
  })

  it("没有活动控件时仍可重绘编辑器", () => {
    document.body.append(renderHtml('<div id="map-root"><div class="map-edit-panel"></div></div>'))
    const root = document.getElementById("map-root")
    mapView._mountRootId = "map-root"
    const teardown = vi.spyOn(mapView, "_teardownInteractiveSurface").mockImplementation(() => {})
    const render = vi.spyOn(mapView, "_render").mockImplementation(() => {
      root.innerHTML = '<div class="map-edit-panel"></div>'
    })

    expect(() => mapView._rerenderEditor()).not.toThrow()
    teardown.mockRestore()
    render.mockRestore()
  })

  it("保留编辑面板的滚动位置和控件焦点", () => {
    document.body.append(renderHtml('<div id="map-root"><div class="map-edit-panel"><select data-layer-active-group="group-1"></select></div></div>'))
    const root = document.getElementById("map-root")
    root.querySelector(".map-edit-panel").scrollTop = 420
    root.querySelector("[data-layer-active-group='group-1']").focus()
    mapView._mountRootId = "map-root"
    const teardown = vi.spyOn(mapView, "_teardownInteractiveSurface").mockImplementation(() => {})
    const render = vi.spyOn(mapView, "_render").mockImplementation(() => {
      root.innerHTML = '<div class="map-edit-panel"><select data-layer-active-group="group-1"></select></div>'
    })

    mapView._rerenderEditor()

    expect(root.querySelector(".map-edit-panel").scrollTop).toBe(420)
    expect(document.activeElement).toBe(root.querySelector("[data-layer-active-group='group-1']"))
    teardown.mockRestore()
    render.mockRestore()
  })

  it("按钮触发局部重绘后仍聚焦同一操作", () => {
    document.body.append(renderHtml('<div id="map-root"><div class="map-edit-panel"><button type="button" data-action="map-layer-toggle-visible" data-id="layer-1">◉</button></div></div>'))
    const root = document.getElementById("map-root")
    root.querySelector("[data-action='map-layer-toggle-visible']").focus()
    mapView._mountRootId = "map-root"
    const teardown = vi.spyOn(mapView, "_teardownInteractiveSurface").mockImplementation(() => {})
    const render = vi.spyOn(mapView, "_render").mockImplementation(() => {
      root.innerHTML = '<div class="map-edit-panel"><button type="button" data-action="map-layer-toggle-visible" data-id="layer-1">○</button></div>'
    })

    mapView._rerenderEditor()

    expect(document.activeElement).toBe(root.querySelector("[data-action='map-layer-toggle-visible']"))
    teardown.mockRestore()
    render.mockRestore()
  })
})
// ============================================================
// 六边形几何
// ============================================================

describe("mapHexRenderer 几何", () => {
  describe("hexToPixel / pixelToHex 往返", () => {
    it("原点 (0,0) → (0,0)", () => {
      const [x, y] = hexToPixel(0, 0, 30)
      expect(x).toBe(0)
      expect(y).toBe(0)
    })

    it("pixelToHex(hexToPixel(q,r)) ≈ (q,r) 对多个坐标", () => {
      const cases = [[0, 0], [1, 0], [0, 1], [3, 2], [-2, 5], [10, 7]]
      for (const [q, r] of cases) {
        const [x, y] = hexToPixel(q, r, 30)
        const [rq, rr] = pixelToHex(x, y, 30)
        // hexRound 可能产生 -0；+0 归一化后比较
        expect(rq + 0).toBe(q + 0)
        expect(rr + 0).toBe(r + 0)
      }
    })

    it("带小数误差的像素坐标能正确 round", () => {
      // (2,3) 的中心点加微小扰动
      const [x, y] = hexToPixel(2, 3, 30)
      const [rq, rr] = pixelToHex(x + 2, y - 1, 30)
      expect(rq).toBe(2)
      expect(rr).toBe(3)
    })
  })

  describe("hexRound", () => {
    it("整数坐标不变", () => {
      expect(hexRound(2, 3)).toEqual([2, 3])
    })

    it("0.5 附近 round 遵循 -q-r-s 约束", () => {
      // (1.4, 1.4): s=-2.8, round→ rq=1,rr=1,rs=-3; dq=.4,dr=.4,ds=.2; dr>ds → rr=-rq-rs=2
      const [q, r] = hexRound(1.4, 1.4)
      expect(q).toBe(1)
      expect(r).toBe(2)
      // 校验六边形约束 q+r+s=0
      expect(q + r + (-q - r)).toBe(0)
    })
  })

  describe("getNeighbors", () => {
    it("返回 6 个邻居", () => {
      const neighbors = getNeighbors(0, 0)
      expect(neighbors).toHaveLength(6)
      // 每个邻居的 q+r+s=0（s=-q-r），邻居应都是合法 hex
      for (const [nq, nr] of neighbors) {
        expect(typeof nq).toBe("number")
        expect(typeof nr).toBe("number")
      }
    })

    it("(3,2) 的邻居含 (4,2) 和 (3,3)", () => {
      const neighbors = getNeighbors(3, 2)
      expect(neighbors).toContainEqual([4, 2])
      expect(neighbors).toContainEqual([3, 3])
    })
  })

  describe("floodFillTerrain", () => {
    it("填充同地形连通区域", () => {
      // 3x3 全 grassland
      const grid = {}
      for (let q = 0; q < 3; q++)
        for (let r = 0; r < 3; r++) grid[`${q},${r}`] = "grassland"
      const getTerrain = (q, r) => grid[`${q},${r}`] || null

      const changes = floodFillTerrain(0, 0, "grassland", "water", getTerrain)
      // 全部 9 格都是 grassland 且连通（邻居定义下 3x3 是否全连通取决于网格形状）
      // 至少起始格应被填充
      expect(changes.length).toBeGreaterThanOrEqual(1)
      expect(changes.every((c) => c.terrain_type === "water")).toBe(true)
      // 起始格在变更里
      expect(changes.some((c) => c.hex_q === 0 && c.hex_r === 0)).toBe(true)
    })

    it("遇到不同地形停止", () => {
      // (0,0) grassland，(1,0) water → 只填 (0,0)
      const grid = { "0,0": "grassland", "1,0": "water" }
      const getTerrain = (q, r) => grid[`${q},${r}`] || null
      const changes = floodFillTerrain(0, 0, "grassland", "forest", getTerrain)
      // 只有 (0,0)，因为邻居 (1,0) 是 water 不匹配
      const filled = changes.map((c) => `${c.hex_q},${c.hex_r}`)
      expect(filled).toContain("0,0")
      expect(filled).not.toContain("1,0")
    })

    it("起始格非目标地形时返回空", () => {
      const getTerrain = () => "water"
      const changes = floodFillTerrain(0, 0, "grassland", "forest", getTerrain)
      expect(changes).toHaveLength(0)
    })
  })

  describe("配置表", () => {
    it("TERRAIN_COLORS 含 PRD §5.5 全部 10 种地形", () => {
      const expected = ["grassland", "forest", "desert", "mountain", "water", "city", "road", "ruin", "secret", "danger"]
      for (const t of expected) {
        expect(TERRAIN_COLORS[t]).toBeDefined()
        expect(TERRAIN_COLORS[t].fill).toMatch(/^#/)
        expect(TERRAIN_COLORS[t].stroke).toMatch(/^#/)
      }
    })

    it("TERRAIN_OPTIONS 与颜色表一致", () => {
      expect(TERRAIN_OPTIONS).toHaveLength(10)
      for (const opt of TERRAIN_OPTIONS) {
        expect(TERRAIN_COLORS[opt.value]).toBeDefined()
      }
    })
  })

  describe("hexCorners", () => {
    it("返回 6 个顶点", () => {
      const corners = hexCorners(30)
      expect(corners).toHaveLength(6)
      // 每个顶点到中心距离 ≈ size（外接圆半径）
      for (const [x, y] of corners) {
        const dist = Math.sqrt(x * x + y * y)
        expect(dist).toBeCloseTo(30, 5)
      }
    })
  })

  describe("drawHexCell", () => {
    function createMockCtx() {
      const calls = {
        beginPath: 0,
        moveTo: [],
        lineTo: [],
        closePath: 0,
        fill: 0,
        stroke: 0,
        save: 0,
        restore: 0,
        setLineDash: [],
        alphaLog: [],
        fillStyle: "",
        strokeStyle: "",
        lineWidth: 0,
      }
      return {
        beginPath: () => { calls.beginPath++ },
        moveTo: (x, y) => { calls.moveTo.push([x, y]) },
        lineTo: (x, y) => { calls.lineTo.push([x, y]) },
        closePath: () => { calls.closePath++ },
        fill: () => { calls.fill++ },
        stroke: () => { calls.stroke++ },
        save: () => { calls.save++ },
        restore: () => { calls.restore++ },
        setLineDash: (dash) => { calls.setLineDash.push(dash) },
        get fillStyle() { return calls.fillStyle },
        set fillStyle(v) { calls.fillStyle = v },
        get strokeStyle() { return calls.strokeStyle },
        set strokeStyle(v) { calls.strokeStyle = v },
        get lineWidth() { return calls.lineWidth },
        set lineWidth(v) { calls.lineWidth = v },
        get globalAlpha() { return calls.globalAlpha },
        set globalAlpha(v) { calls.alphaLog.push(v); calls.globalAlpha = v },
        _calls: calls,
      }
    }

    it("绘制 6 顶点路径并应用样式", () => {
      const ctx = createMockCtx()
      drawHexCell(ctx, 1, 2, 30, { fill: "#7CB342", stroke: "#558B2F", lineWidth: 2 }, 10, 20, 1)
      expect(ctx._calls.beginPath).toBe(1)
      expect(ctx._calls.moveTo).toHaveLength(1)
      expect(ctx._calls.lineTo).toHaveLength(5)
      expect(ctx._calls.closePath).toBe(1)
      expect(ctx._calls.fill).toBe(1)
      expect(ctx._calls.stroke).toBe(1)
      expect(ctx._calls.fillStyle).toBe("#7CB342")
      expect(ctx._calls.strokeStyle).toBe("#558B2F")
      expect(ctx._calls.lineWidth).toBe(2)

      const [cx, cy] = hexToPixel(1, 2, 30)
      const [vx, vy] = hexCorners(30)[0]
      const [mx, my] = ctx._calls.moveTo[0]
      expect(mx).toBeCloseTo(cx + 10 + vx, 5)
      expect(my).toBeCloseTo(cy + 20 + vy, 5)
    })

    it("应用 lineDash 并在绘制后重置", () => {
      const ctx = createMockCtx()
      drawHexCell(ctx, 0, 0, 30, { stroke: "#000", lineDash: [4, 3] }, 0, 0, 1)
      expect(ctx._calls.setLineDash).toContainEqual([4, 3])
      expect(ctx._calls.setLineDash).toContainEqual([])
    })

    it("应用 opacity 并通过 save/restore 隔离", () => {
      const ctx = createMockCtx()
      drawHexCell(ctx, 0, 0, 30, { fill: "#f00" }, 0, 0, 0.5)
      expect(ctx._calls.save).toBeGreaterThanOrEqual(1)
      expect(ctx._calls.restore).toBeGreaterThanOrEqual(1)
      expect(ctx._calls.alphaLog).toContain(0.5)
      expect(ctx._calls.alphaLog).toContain(1)
    })
  })

  describe("mapHexRenderer 聚焦透明度", () => {
    it.each([
      {
        name: "drawTerrain",
        fn: drawTerrain,
        args: (ctx) => [ctx, [{ hex_q: 0, hex_r: 0, terrain_type: "grassland" }, { hex_q: 1, hex_r: 0, terrain_type: "water" }], 30, 0, 0, (q, r) => (q === 0 && r === 0 ? 0.3 : 1)],
        expected: [0.3, 1],
      },
      {
        name: "drawBindings",
        fn: drawBindings,
        args: (ctx) => [ctx, [{ hex_q: 0, hex_r: 0, is_center: true }, { hex_q: 1, hex_r: 0, is_center: false }], 30, 0, 0, true, (q, r) => (q === 0 && r === 0 ? 0.4 : 1)],
        expected: [0.4, 1],
      },
      {
        name: "drawPendingTerrain",
        fn: drawPendingTerrain,
        args: (ctx) => [ctx, [{ hex_q: 0, hex_r: 0, terrain_type: "water" }], 30, 0, 0, () => 0.5],
        expected: [0.5 * 0.4],
      },
      {
        name: "drawPendingBindings",
        fn: drawPendingBindings,
        args: (ctx) => [ctx, [{ hex_q: 0, hex_r: 0, is_center: false }], 30, 0, 0, () => 0.6],
        expected: [0.6],
      },
      {
        name: "drawHoverHighlight",
        fn: drawHoverHighlight,
        args: (ctx) => [ctx, 0, 0, 30, 0, 0, 0.5],
        expected: [0.5],
      },
      {
        name: "drawTerritories",
        fn: drawTerritories,
        args: (ctx) => [ctx, [{ faction_id: "f1", hexes: [{ hex_q: 0, hex_r: 0 }] }], 30, 0, 0, {}, () => 0.6],
        expected: [0.6],
      },
    ])("$name 接受 getOpacity 回调并应用不同透明度", ({ fn, args, expected }) => {
      const ctx = createCanvasMock()
      fn(...args(ctx))
      for (const alpha of expected) {
        expect(ctx.alphaLog).toContain(alpha)
      }
    })
  })

  describe("mapHexRenderer 绘制辅助", () => {
    it.each([
      {
        name: "drawPendingTerrain",
        fn: drawPendingTerrain,
        args: (ctx) => [ctx, [{ hex_q: 0, hex_r: 0, terrain_type: "water" }], 30, 0, 0],
        expected: ["beginPath", "fill"],
      },
      {
        name: "drawPendingBindings",
        fn: drawPendingBindings,
        args: (ctx) => [ctx, [{ hex_q: 0, hex_r: 0, is_center: true }], 30, 0, 0],
        expected: ["beginPath", "stroke"],
      },
      {
        name: "drawHoverHighlight",
        fn: drawHoverHighlight,
        args: (ctx) => [ctx, 1, 1, 30, 0, 0],
        expected: ["stroke"],
      },
    ])("$name 绘制对应图形", ({ fn, args, expected }) => {
      const ctx = createCanvasMock()
      fn(...args(ctx))
      for (const method of expected) {
        expect(ctx[method]).toHaveBeenCalled()
      }
    })
  })
})

// ============================================================
// mapState 状态机
// ============================================================

describe("mapState 状态机", () => {
  it("初始状态", () => {
    expect(mapState.currentMapId).toBeNull()
    expect(mapState.mode).toBe("browse")
    expect(mapState.activeTool).toBe("brush")
    expect(mapState.selectedTerrain).toBe("grassland")
    expect(mapState.selectedLocationEntityId).toBeNull()
    expect(mapState.pendingTerrainChanges).toEqual({})
    expect(mapState.undoStack).toEqual([])
    expect(mapState.pendingBindings).toEqual({})
    expect(mapState.dragDrawing).toBe(false)
    expect(mapState.lastDragHex).toBeNull()
    expect(mapState.hoveredHex).toBeNull()
    expect(mapState.selectedHex).toBeNull()
    expect(mapState.bindCenterMode).toBe(false)
  })

  it("stageTerrainChange 记录变更", () => {
    stageTerrainChange(1, 2, "water")
    stageTerrainChange(3, 4, "mountain")
    expect(Object.keys(mapState.pendingTerrainChanges)).toHaveLength(2)
    expect(mapState.pendingTerrainChanges["1,2"]).toMatchObject({
      hex_q: 1, hex_r: 2, terrain_type: "water",
    })
  })

  it("同格二次 stage 覆盖旧值", () => {
    stageTerrainChange(1, 1, "water")
    stageTerrainChange(1, 1, "forest")
    expect(mapState.pendingTerrainChanges["1,1"].terrain_type).toBe("forest")
  })

  it("consumePendingChanges 清空 pending 并压栈", () => {
    stageTerrainChange(1, 1, "water")
    stageTerrainChange(2, 2, "forest")
    const changes = consumePendingChanges()
    expect(changes).toHaveLength(2)
    expect(mapState.pendingTerrainChanges).toEqual({})
    expect(mapState.undoStack).toHaveLength(1)
  })

  it("consumePendingChanges 空时不压栈", () => {
    const changes = consumePendingChanges()
    expect(changes).toHaveLength(0)
    expect(mapState.undoStack).toHaveLength(0)
  })

  it("popUndo LIFO", () => {
    stageTerrainChange(1, 1, "water")
    consumePendingChanges()
    stageTerrainChange(2, 2, "forest")
    consumePendingChanges()
    const last = popUndo()
    expect(last).toHaveLength(1)
    expect(last[0].terrain_type).toBe("forest")
    expect(mapState.undoStack).toHaveLength(1)
  })

  it("popUndo 空栈返回 null", () => {
    expect(popUndo()).toBeNull()
  })

  it("resetMapState 恢复初始", () => {
    stageTerrainChange(1, 1, "water")
    consumePendingChanges()
    mapState.mode = "edit"
    mapState.activeTool = "bucket"
    mapState.currentMapId = "m1"
    mapState.selectedLocationEntityId = "loc1"
    mapState.pendingBindings["1,2"] = { location_entity_id: "loc1", hex_q: 1, hex_r: 2, is_center: true }
    mapState.dragDrawing = true
    mapState.lastDragHex = "1,1"
    mapState.hoveredHex = { hex_q: 1, hex_r: 1 }
    mapState.selectedHex = { hex_q: 2, hex_r: 2 }
    mapState.bindCenterMode = true
    resetMapState()
    expect(mapState.currentMapId).toBeNull()
    expect(mapState.mode).toBe("browse")
    expect(mapState.activeTool).toBe("brush")
    expect(mapState.selectedLocationEntityId).toBeNull()
    expect(mapState.undoStack).toEqual([])
    expect(mapState.pendingTerrainChanges).toEqual({})
    expect(mapState.pendingBindings).toEqual({})
    expect(mapState.dragDrawing).toBe(false)
    expect(mapState.lastDragHex).toBeNull()
    expect(mapState.hoveredHex).toBeNull()
    expect(mapState.selectedHex).toBeNull()
    expect(mapState.bindCenterMode).toBe(false)
  })

  it("stageTerrainChange 带 elevation", () => {
    stageTerrainChange(0, 0, "mountain", 5)
    expect(mapState.pendingTerrainChanges["0,0"].elevation).toBe(5)
  })

  it("stageBindingChange 记录绑定变更", () => {
    stageBindingChange("loc1", 1, 2, true)
    expect(mapState.pendingBindings["1,2"]).toMatchObject({
      location_entity_id: "loc1", hex_q: 1, hex_r: 2, is_center: true,
    })
  })

  it("stageBindingChange 同一格再次点击取消", () => {
    stageBindingChange("loc1", 1, 2, false)
    stageBindingChange("loc1", 1, 2, false)
    expect(mapState.pendingBindings["1,2"]).toBeUndefined()
  })

  it("stageBindingChange 同一格 isCenter 不同则覆盖", () => {
    stageBindingChange("loc1", 1, 2, false)
    stageBindingChange("loc1", 1, 2, true)
    expect(mapState.pendingBindings["1,2"]).toMatchObject({
      location_entity_id: "loc1", hex_q: 1, hex_r: 2, is_center: true,
    })
  })

  it("consumePendingBindings 清空并返回数组", () => {
    stageBindingChange("loc1", 1, 2, true)
    const bindings = consumePendingBindings()
    expect(bindings).toHaveLength(1)
    expect(mapState.pendingBindings).toEqual({})
  })

  it("setHoveredHex / clearHoveredHex", () => {
    setHoveredHex(3, 4)
    expect(mapState.hoveredHex).toEqual({ hex_q: 3, hex_r: 4 })
    clearHoveredHex()
    expect(mapState.hoveredHex).toBeNull()
  })

  it("setSelectedHex / clearSelectedHex", () => {
    setSelectedHex(5, 6)
    expect(mapState.selectedHex).toEqual({ hex_q: 5, hex_r: 6 })
    clearSelectedHex()
    expect(mapState.selectedHex).toBeNull()
  })

  it("拖拽状态 start/end", () => {
    startDragDraw()
    expect(mapState.dragDrawing).toBe(true)
    endDragDraw()
    expect(mapState.dragDrawing).toBe(false)
  })

  it("recordDragHex 去重", () => {
    startDragDraw()
    expect(recordDragHex(1, 1)).toBe(true)
    expect(recordDragHex(1, 1)).toBe(false)
    expect(recordDragHex(1, 2)).toBe(true)
    endDragDraw()
    expect(mapState.lastDragHex).toBeNull()
  })
})

// ============================================================
// mapView 列表渲染 + XSS
// ============================================================

describe("mapView 列表渲染", () => {
  it("加载地图列表调用 listMaps", async () => {
    globalThis.state.currentProjectId = "p1"
    api.world.listMaps.mockResolvedValue({
      items: [{ id: "m1", name: "九州", map_type: "world", grid_width: 30, grid_height: 20 }],
      total: 1,
    })

    await mapView._loadMaps()

    expect(api.world.listMaps).toHaveBeenCalledWith({
      novel_id: "p1",
      status: "active",
      skip: 0,
      limit: 500,
    })
    expect(mapView._maps).toHaveLength(1)
    expect(mapView._maps[0].name).toBe("九州")
  })

  it("地点、标记和势力选择器只加载已采用实体", async () => {
    globalThis.state.currentProjectId = "p1"
    api.world.listEntities.mockImplementation(async (params) => ({
      items: params.display_state === "active"
        ? [{ id: `active-${params.entity_type}`, entity_type: params.entity_type }]
        : [{
            id: `shadow-${params.entity_type}`,
            entity_type: params.entity_type,
            status: "candidate",
            content_json: { _meta: { compatibility_shadow: true } },
          }],
    }))

    await mapView._loadLocations()
    await mapView._loadAllEntities()

    expect(api.world.listEntities).toHaveBeenCalledTimes(6)
    for (const [params] of api.world.listEntities.mock.calls) {
      expect(params).toMatchObject({
        novel_id: "p1",
        display_state: "active",
        skip: 0,
        limit: 50,
      })
    }
    expect(mapView._locations.map((entity) => entity.id)).toEqual(["active-location"])
    expect(mapView._allEntities.every((entity) => entity.id.startsWith("active-"))).toBe(true)
    expect(mapView._allEntities.some((entity) => entity.id.startsWith("shadow-"))).toBe(false)
  })

  it("listMaps 失败时显示地图列表加载失败提示", async () => {
    globalThis.state.currentProjectId = "p1"
    api.world.listMaps.mockRejectedValue(new Error("网络失败"))
    await mapView._loadMaps()
    const container = renderHtml(mapView._renderEmpty())

    expect(mapView._maps).toEqual([])
    expect(container.textContent).toContain("地图列表加载失败")
    expect(container.textContent).toContain("可稍后重试")
    expect(toast).toHaveBeenCalledWith("地图列表加载失败，可稍后重试", "warning")
  })

  it("_renderEmpty 显示创建入口", () => {
    const html = mapView._renderEmpty()
    expect(html).toContain("创建世界地图")
    expect(html).toContain("map-create-world")
    expect(html).not.toContain("<script")
  })

  it("_renderList 渲染地图行", () => {
    mapView._maps = [
      { id: "m1", name: "九州世界", map_type: "world", grid_width: 30, grid_height: 20 },
    ]
    const html = mapView._renderList()
    expect(html).toContain("九州世界")
    expect(html).toContain("world")
    expect(html).toContain("30×20")
    expect(html).toContain('data-id="m1"')
  })

  it("XSS：地图名中的 HTML 特殊字符被转义", () => {
    const evil = `<img src=x onerror=alert(1)>`
    mapView._maps = [
      { id: "m1", name: evil, map_type: "world", grid_width: 3, grid_height: 3 },
    ]
    const html = mapView._renderList()
    // 原始恶意字符串（未转义的 <img> 标签）不应出现
    expect(html).not.toContain(evil)
    // < > 应被转义，使 <img> 无法被解析为 HTML 元素（关键 XSS 防护）
    expect(html).toContain("&lt;img")
    expect(html).not.toContain("<img")
    expect(html).toContain("&gt;")
  })

  it("_renderMapShell 面包屑转义", () => {
    mapView._state = {
      map: { id: "m1", name: "地图", hex_size: 30, grid_width: 5, grid_height: 5 },
      breadcrumbs: [{ id: "m1", name: `<b>恶意</b>` }],
      tiles: [],
      location_bindings: [],
    }
    mapView._maps = []
    mapView._locations = []
    const html = mapView._renderMapShell()
    expect(html).not.toContain("<b>恶意</b>")
    expect(html).toContain("&lt;b&gt;")
  })
})

describe("mapView Leaflet overlay alignment", () => {
  it("mounts the canvas as a fixed container overlay, not inside a movable Leaflet pane", async () => {
    const overlayPane = document.createElement("div")
    overlayPane.className = "leaflet-overlay-pane"
    const container = document.createElement("div")
    container.id = "map-leaflet"
    container.appendChild(overlayPane)
    Object.defineProperty(container, "clientWidth", { value: 640, configurable: true })
    Object.defineProperty(container, "clientHeight", { value: 420, configurable: true })
    document.body.appendChild(container)

    const originalGetContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = vi.fn(() => createCanvasMock({
      methods: ["setTransform", "clearRect", "translate", "scale"],
    }))

    const { leafletApi } = createLeafletHarness(container)

    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      location_bindings: [],
      markers: [],
      territories: [],
    }

    try {
      await mapView._initLeaflet(async () => leafletApi)

      expect(mapView._canvas?.parentElement).toBe(container)
      expect(overlayPane.contains(mapView._canvas)).toBe(false)
    } finally {
      mapView._teardownInteractiveSurface()
      mapView._state = null
      HTMLCanvasElement.prototype.getContext = originalGetContext
    }
  })

  it("uses the loaded module without injecting CDN resources or window globals", async () => {
    const freshMapView = await importFreshMapView()
    const container = document.createElement("div")
    container.id = "map-leaflet"
    Object.defineProperty(container, "clientWidth", { value: 640, configurable: true })
    Object.defineProperty(container, "clientHeight", { value: 420, configurable: true })
    document.body.appendChild(container)

    const originalGetContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = vi.fn(() => createCanvasMock({
      methods: ["setTransform", "clearRect", "translate", "scale"],
    }))
    const { leafletApi, leafletMap } = createLeafletHarness(container)
    freshMapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      location_bindings: [],
      markers: [],
      territories: [],
    }

    try {
      await freshMapView._initLeaflet(async () => leafletApi)

      expect(leafletApi.map).toHaveBeenCalledWith(container, expect.objectContaining({
        crs: leafletApi.CRS.Simple,
        minZoom: -12,
        attributionControl: false,
      }))
      expect(freshMapView._leaflet.setMinZoom).toHaveBeenCalledWith(-5)
      expect(freshMapView._leaflet).toBe(leafletMap)
      expect(document.querySelector('[data-leaflet-dynamic="true"]')).toBeNull()
      expect(globalThis.L).toBeUndefined()
    } finally {
      freshMapView._teardownInteractiveSurface()
      freshMapView._state = null
      HTMLCanvasElement.prototype.getContext = originalGetContext
    }
  })

  it("uses native label buttons for location, layout item, and cluster activation", async () => {
    const freshMapView = await importFreshMapView()
    const container = document.createElement("div")
    Object.defineProperty(container, "clientWidth", { value: 640, configurable: true })
    Object.defineProperty(container, "clientHeight", { value: 180, configurable: true })
    const markers = []
    freshMapView._state = { map: { hex_size: 30 }, markers: [] }
    freshMapView._leaflet = {
      eachLayer: vi.fn(),
      getZoom: vi.fn(() => 0),
      getContainer: vi.fn(() => container),
      latLngToContainerPoint: vi.fn(() => ({ x: 60, y: 60 })),
      containerPointToLatLng: vi.fn(([x, y]) => ({ lat: y, lng: x })),
    }
    const divIcon = vi.fn((options) => options)
    freshMapView._leafletApi = {
      latLng: vi.fn((lat, lng) => ({ lat, lng })),
      divIcon,
      marker: vi.fn(() => {
        const marker = { addTo: vi.fn(() => marker) }
        markers.push(marker)
        return marker
      }),
    }
    freshMapView._buildMapLabelItems = vi.fn(() => [
      {
        item_id: "location:loc-1", item_kind: "fact", fact_status: "confirmed",
        title: "洛阳外城", object_type: "location", dynamic_type: "location",
        priority: 100, target_entity_id: "loc-1", source_kind: "location",
        source_id: "loc-1", q: 0, r: 0, opacity: 1, anchor: { x: 30, y: 90 },
      },
      {
        item_id: "marker:marker-1", item_kind: "fact", fact_status: "confirmed",
        title: "城门守卫", object_type: "character", dynamic_type: "character",
        priority: 100, target_entity_id: "char-1", source_kind: "marker",
        source_id: "marker-1", q: 1, r: 1, opacity: 1, anchor: { x: 150, y: 90 },
      },
      ...Array.from({ length: 8 }, (_, index) => ({
        item_id: `filler:${index}`, item_kind: "fact", fact_status: "confirmed",
        title: `事件 ${index}`, object_type: "event", dynamic_type: "event",
        priority: 0, source_kind: "marker", source_id: `filler-${index}`,
        q: index + 2, r: 1, opacity: 1,
        anchor: { x: 260 + index * 45, y: index % 2 ? 130 : 50 },
      })),
    ])
    freshMapView._hasDetailMap = vi.fn(() => false)
    const openDetail = vi.spyOn(freshMapView, "_onCenterClick").mockImplementation(() => {})
    const openLayoutItem = vi.spyOn(freshMapView, "_openMapLayoutItem").mockImplementation(() => {})
    const openCluster = vi.spyOn(freshMapView, "_showLocationCluster").mockImplementation(() => {})

    freshMapView._renderCenterLabels()

    const iconButtons = divIcon.mock.calls.map(([options]) => options.html)
    expect(iconButtons.every((button) => button instanceof HTMLButtonElement)).toBe(true)
    const locationButton = iconButtons.find((button) => button.dataset.id === "loc-1")
    const markerButton = iconButtons.find((button) => button.dataset.id === "marker-1")
    const clusterButton = iconButtons.find((button) => button.dataset.kind === "cluster")
    expect(locationButton).toMatchObject({ type: "button", tabIndex: 0 })
    expect(locationButton.dataset).toMatchObject({
      kind: "location", id: "loc-1", q: "0", r: "0",
    })
    expect(locationButton.textContent).toContain("洛阳外城")
    expect(locationButton.getAttribute("aria-label")).toBe("洛阳外城")
    expect(locationButton.querySelector(".map-center-drill")?.getAttribute("aria-hidden")).toBe("true")
    expect(markerButton.dataset).toMatchObject({
      kind: "marker", id: "marker-1", q: "1", r: "1",
    })
    expect(clusterButton).toBeInstanceOf(HTMLButtonElement)

    const eventBoundary = document.createElement("div")
    const leakedEvents = []
    for (const eventType of ["pointerdown", "mousedown", "touchstart", "dblclick", "contextmenu"]) {
      eventBoundary.addEventListener(eventType, () => leakedEvents.push(eventType))
    }
    eventBoundary.append(locationButton, markerButton, clusterButton)
    document.body.appendChild(eventBoundary)
    locationButton.focus()
    expect(document.activeElement).toBe(locationButton)
    for (const eventType of ["pointerdown", "mousedown", "touchstart", "dblclick", "contextmenu"]) {
      locationButton.dispatchEvent(new Event(eventType, { bubbles: true, cancelable: true }))
    }
    expect(leakedEvents).toEqual([])
    expect(openDetail).not.toHaveBeenCalled()
    // happy-dom 不会为 Enter 合成浏览器默认 click，因此显式执行该默认动作。
    locationButton.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
    locationButton.click()
    locationButton.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", bubbles: true }))
    expect(openDetail).toHaveBeenCalledOnce()
    expect(openDetail).toHaveBeenCalledWith("loc-1")
    markerButton.click()
    expect(openLayoutItem).toHaveBeenCalledWith({
      kind: "marker", id: "marker-1", q: 1, r: 1,
    })
    clusterButton.click()
    expect(openCluster).toHaveBeenCalledWith(clusterButton.dataset.id)
    expect(markers.every((marker) => marker.addTo.mock.calls.length === 1)).toBe(true)
  })

  it("reuses one in-flight Leaflet module load across concurrent initialization", async () => {
    const freshMapView = await importFreshMapView()
    const container = document.createElement("div")
    container.id = "map-leaflet"
    Object.defineProperty(container, "clientWidth", { value: 640, configurable: true })
    Object.defineProperty(container, "clientHeight", { value: 420, configurable: true })
    document.body.appendChild(container)

    const originalGetContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = vi.fn(() => createCanvasMock({
      methods: ["setTransform", "clearRect", "translate", "scale"],
    }))
    freshMapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      location_bindings: [],
      markers: [],
      territories: [],
    }
    const { leafletApi } = createLeafletHarness(container)
    let resolveImport
    const importer = vi.fn(() => new Promise((resolve) => {
      resolveImport = resolve
    }))
    const load = createRetryableLeafletLoader(importer)

    try {
      const first = freshMapView._initLeaflet(load)
      const second = freshMapView._initLeaflet(load)
      await Promise.resolve()
      expect(importer).toHaveBeenCalledTimes(1)
      resolveImport(leafletApi)
      await Promise.all([first, second])

      expect(leafletApi.map).toHaveBeenCalledTimes(1)
    } finally {
      freshMapView._teardownInteractiveSurface()
      freshMapView._state = null
      HTMLCanvasElement.prototype.getContext = originalGetContext
    }
  })

  it("renders the existing failure state with an in-place retry", async () => {
    const freshMapView = await importFreshMapView()
    const container = document.createElement("div")
    container.id = "map-leaflet"
    Object.defineProperty(container, "clientWidth", { value: 640, configurable: true })
    Object.defineProperty(container, "clientHeight", { value: 420, configurable: true })
    document.body.appendChild(container)
    const originalGetContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = vi.fn(() => createCanvasMock({
      methods: ["setTransform", "clearRect", "translate", "scale"],
    }))
    freshMapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      location_bindings: [],
      markers: [],
      territories: [],
    }
    const { leafletApi } = createLeafletHarness(container)
    const load = createRetryableLeafletLoader(
      vi.fn()
        .mockRejectedValueOnce(new Error("chunk unavailable"))
        .mockResolvedValueOnce(leafletApi),
    )

    try {
      await freshMapView._initLeaflet(load)

      expect(container.textContent).toContain("地图引擎加载失败")
      expect(container.textContent).toContain("其他页面不受影响")
      expect(freshMapView._leaflet).toBeNull()
      container.querySelector("button").click()

      await vi.waitFor(() => expect(leafletApi.map).toHaveBeenCalledTimes(1))
      expect(container.querySelector('[data-leaflet-load-failure="true"]')).toBeNull()
      expect(freshMapView._leaflet).not.toBeNull()
    } finally {
      freshMapView._teardownInteractiveSurface()
      freshMapView._state = null
      HTMLCanvasElement.prototype.getContext = originalGetContext
    }
  })

  it("throttles viewport redraws through requestAnimationFrame", () => {
    const queued = []
    const originalRaf = globalThis.requestAnimationFrame
    const originalCancel = globalThis.cancelAnimationFrame
    globalThis.requestAnimationFrame = vi.fn((callback) => {
      queued.push(callback)
      return queued.length
    })
    globalThis.cancelAnimationFrame = vi.fn()
    const redraw = vi.spyOn(mapView, "_redraw").mockImplementation(() => {})

    try {
      mapView._scheduleRedraw()
      mapView._scheduleRedraw()

      expect(globalThis.requestAnimationFrame).toHaveBeenCalledTimes(1)
      expect(redraw).not.toHaveBeenCalled()

      queued[0]()
      expect(redraw).toHaveBeenCalledTimes(1)
    } finally {
      redraw.mockRestore()
      globalThis.requestAnimationFrame = originalRaf
      globalThis.cancelAnimationFrame = originalCancel
      mapView._redrawFrame = null
    }
  })
})

describe("mapView dynamic state loading", () => {
  it("switching Scene refreshes dynamic layers without reloading static state", async () => {
    state.currentProjectId = "p1"
    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [{ hex_q: 0, hex_r: 0, terrain_type: "grassland" }],
      location_bindings: [{ location_entity_id: "loc1", hex_q: 0, hex_r: 0, is_center: true }],
      markers: [{ id: "old-marker" }],
      territories: [],
      candidate_location_bindings: [],
      candidate_markers: [],
      candidate_territories: [],
    }
    mapView._rebuildIndexes()
    setCurrentScene("s2")
    api.world.getMapDynamicState.mockResolvedValue({
      markers: [{ id: "new-marker", entity_id: "c1" }],
      territories: [{ id: "territory-1", faction_entity_id: "f1" }],
      candidate_location_bindings: [{ id: "candidate-binding", hex_q: 1, hex_r: 1 }],
      candidate_markers: [{ id: "candidate-marker" }],
      candidate_territories: [],
      scene: { id: "s2", index: 2, title: "第二 Scene" },
    })

    await mapView._reloadWithScene()

    expect(api.world.getMapDynamicState).toHaveBeenCalledWith("m1", "p1", "s2")
    expect(api.world.getMapState).not.toHaveBeenCalled()
    expect(mapView._state.tiles).toEqual([{ hex_q: 0, hex_r: 0, terrain_type: "grassland" }])
    expect(mapView._state.location_bindings).toEqual([
      { location_entity_id: "loc1", hex_q: 0, hex_r: 0, is_center: true },
    ])
    expect(mapView._state.markers).toEqual([{ id: "new-marker", entity_id: "c1" }])
    expect(mapView._state.scene).toEqual({ id: "s2", index: 2, title: "第二 Scene" })
  })
})

describe("mapView 弹窗失败保留本地输入", () => {
  it("场景切换被拒绝时返回 false 并保留选择弹窗", async () => {
    mapState.sceneList = [{ id: "s1", index: 1, title: "开端" }]
    mapView._mountContext = { onSceneChange: vi.fn(async () => false) }
    mapView._showScenePicker()
    document.body.innerHTML = showModal.mock.calls[0][1].html

    await expect(showModal.mock.calls[0][2][0].handler()).resolves.toBe(false)
    expect(closeModal).not.toHaveBeenCalled()
  })

  it("场景切换接口失败时返回 false 供原位重试", async () => {
    mapState.sceneList = [{ id: "s1", index: 1, title: "开端" }]
    mapView._mountContext = { onSceneChange: vi.fn(async () => { throw new Error("切换失败") }) }
    mapView._showScenePicker()
    document.body.innerHTML = showModal.mock.calls[0][1].html

    await expect(showModal.mock.calls[0][2][0].handler()).resolves.toBe(false)
    expect(toast).toHaveBeenCalledWith("切换场景失败：切换失败", "error")
    expect(closeModal).not.toHaveBeenCalled()
  })

  it("创建世界地图的本地校验和接口失败都返回 false", async () => {
    state.currentProjectId = "p1"
    mapView._showCreateWorldForm()
    document.body.innerHTML = showModal.mock.calls[0][1].html
    const handler = showModal.mock.calls[0][2][0].handler

    await expect(handler()).resolves.toBe(false)
    document.getElementById("map-create-name").value = "九州"
    api.world.createMap.mockRejectedValueOnce(new Error("网络失败"))
    await expect(handler()).resolves.toBe(false)
  })

  it("创建地点详图接口失败时返回 false", async () => {
    state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1" } }
    mapView._locationById = new Map([["loc1", { id: "loc1", name: "廷根" }]])
    api.world.createMap.mockRejectedValueOnce(new Error("网络失败"))
    mapView._showCreateDetailForm("loc1")
    document.body.innerHTML = showModal.mock.calls[0][1].html

    await expect(showModal.mock.calls[0][2][0].handler()).resolves.toBe(false)
  })

  it("详图创建成功但快速生成失败时收口且不允许重复创建", async () => {
    state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1" } }
    mapView._locationById = new Map([["loc1", { id: "loc1", name: "廷根" }]])
    api.world.createMap.mockResolvedValueOnce({ id: "detail-1" })
    api.world.generateMap.mockRejectedValueOnce(new Error("生成服务不可用"))
    const openMap = vi.spyOn(mapView, "_openMap").mockResolvedValue(true)
    mapView._showCreateDetailForm("loc1")
    document.body.innerHTML = showModal.mock.calls[0][1].html

    await expect(showModal.mock.calls[0][2][0].handler()).resolves.toBe(true)
    expect(api.world.createMap).toHaveBeenCalledTimes(1)
    expect(closeModal).toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(
      "详图已创建，但快速生成失败：生成服务不可用",
      "warning",
    )
    expect(openMap).toHaveBeenCalledWith("detail-1")
    openMap.mockRestore()
  })

  it("创建世界地图等待期间被新弹窗替换时不提示或打开旧结果", async () => {
    state.currentProjectId = "p1"
    let resolveCreate
    api.world.createMap.mockImplementationOnce(() => new Promise((resolve) => { resolveCreate = resolve }))
    const openMap = vi.spyOn(mapView, "_openMap").mockResolvedValue(true)
    mapView._showCreateWorldForm()
    document.body.innerHTML = showModal.mock.calls[0][1].html
    document.getElementById("map-create-name").value = "旧世界"
    const pending = showModal.mock.calls[0][2][0].handler()
    await vi.waitFor(() => expect(resolveCreate).toBeTypeOf("function"))
    document.getElementById("map-create-name").replaceWith(document.createElement("input"))
    resolveCreate({ id: "old-map" })

    await expect(pending).resolves.toBe(true)
    expect(openMap).not.toHaveBeenCalled()
    expect(closeModal).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalledWith("世界地图已创建", "success")
    openMap.mockRestore()
  })

  it("图层缩放范围无效时返回 false", async () => {
    mapView._state = { map: { id: "m1" } }
    mapView._layerTree = { nodes: [{
      id: "layer-1",
      node_type: "group",
      name: "设定层",
      visible: true,
      locked: false,
      opacity: 1,
      sort_order: 0,
    }] }
    mapView._showLayerNodeSettings("layer-1")
    document.body.innerHTML = showModal.mock.calls[0][1].html
    document.getElementById("map-layer-node-min-zoom").value = "2"
    document.getElementById("map-layer-node-max-zoom").value = "1"

    expect(showModal.mock.calls[0][2][0].handler()).toBe(false)
  })
})

describe("mapView 地图设置", () => {
  it("_renderMapShell 显示设置按钮", () => {
    mapView._state = {
      map: { id: "m1", name: "九州", hex_size: 30, grid_width: 5, grid_height: 5 },
      breadcrumbs: [],
      tiles: [],
      location_bindings: [],
    }
    mapView._maps = []
    const html = mapView._renderMapShell()
    expect(html).toContain("data-action=\"map-settings\"")
    expect(html).toContain("地图设置")
  })

  it("_showSettingsModal 字段预填充当前名称和描述", () => {
    mapView._state = {
      map: { id: "m1", name: "九州", description: "古都世界", hex_size: 30, grid_width: 5, grid_height: 5 },
      breadcrumbs: [],
      tiles: [],
      location_bindings: [],
    }
    mapView._showSettingsModal()
    expect(showModal).toHaveBeenCalled()
    const formHtml = showModal.mock.calls[0][1].html
    expect(formHtml).toContain('value="九州"')
    expect(formHtml).toContain("古都世界")
    expect(formHtml).toContain("上级地图")
    expect(formHtml).toContain("移动地图只修改层级")
  })

  it("_showSettingsModal 可将既有地图移到另一层级且不列出后代", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._state = {
      map: { id: "m1", name: "廷根城", description: "城市图", parent_map_id: null },
    }
    mapView._maps = [
      { id: "m0", name: "鲁恩世界", parent_map_id: null },
      { id: "m1", name: "廷根城", parent_map_id: null },
      { id: "m2", name: "教堂详图", parent_map_id: "m1" },
    ]
    mapView._locations = [{ id: "loc-tingen", name: "廷根市" }]
    api.world.updateMap.mockResolvedValue({})
    api.world.getMapState.mockResolvedValue({
      map: { id: "m1", name: "廷根城", parent_map_id: "m0", parent_entity_id: "loc-tingen" },
      breadcrumbs: [],
      tiles: [],
      location_bindings: [],
    })
    api.world.listMaps.mockResolvedValue({ items: [], total: 0 })

    mapView._showSettingsModal()
    const formHtml = showModal.mock.calls[0][1].html
    expect(formHtml).toContain('value="m0"')
    expect(formHtml).not.toContain('value="m2"')
    document.body.innerHTML = `
      <input id="map-settings-name" value="廷根城" />
      <textarea id="map-settings-desc">城市图</textarea>
      <select id="map-settings-parent-map"><option value="m0" selected>鲁恩世界</option></select>
      <select id="map-settings-parent-entity"><option value="loc-tingen" selected>廷根市</option></select>
      <div id="map-root"></div>
    `

    await showModal.mock.calls[0][2][0].handler()

    expect(api.world.updateMap).toHaveBeenCalledWith("m1", {
      name: "廷根城",
      description: "城市图",
      parent_map_id: "m0",
      parent_entity_id: "loc-tingen",
    }, "p1")
  })

  it("_showSettingsModal 保存时空名称给出警告", async () => {
    mapView._state = { map: { id: "m1", name: "九州" } }
    document.body.innerHTML = `
      <input id="map-settings-name" value="" />
      <textarea id="map-settings-desc"></textarea>
    `
    mapView._showSettingsModal()
    const handler = showModal.mock.calls[0][2][0].handler
    await expect(handler()).resolves.toBe(false)
    expect(toast).toHaveBeenCalledWith("请输入地图名称", "warning")
    expect(api.world.updateMap).not.toHaveBeenCalled()
  })

  it("_showSettingsModal 保存成功调用 updateMap 并重载", async () => {
    globalThis.state.currentProjectId = "p1"
    mapState.sceneList = [{ id: "s1", index: 1, title: "开端" }]
    mapView._state = { map: { id: "m1", name: "九州", description: "古都" } }
    api.world.updateMap.mockResolvedValue({})
    api.world.getMapState.mockResolvedValue({
      map: { id: "m1", name: "新九州", description: "新描述", hex_size: 30, grid_width: 5, grid_height: 5 },
      breadcrumbs: [],
      tiles: [],
      location_bindings: [],
    })
    api.world.listMaps.mockResolvedValue({ items: [], total: 0 })
    document.body.innerHTML = `
      <input id="map-settings-name" value="新九州" />
      <textarea id="map-settings-desc">新描述</textarea>
      <div id="map-root"></div>
    `
    mapView._showSettingsModal()
    const handler = showModal.mock.calls[0][2][0].handler
    await handler()
    expect(api.world.updateMap).toHaveBeenCalledWith("m1", { name: "新九州", description: "新描述" }, "p1")
    expect(closeModal).toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("地图信息已更新", "success")
    expect(mapView._state?.map?.name).toBe("新九州")
    expect(mapState.sceneList).toEqual([{ id: "s1", index: 1, title: "开端" }])
  })

  it("_showSettingsModal 保存失败 toast 错误", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1", name: "九州" } }
    api.world.updateMap.mockRejectedValue(new Error("网络失败"))
    document.body.innerHTML = `
      <input id="map-settings-name" value="新九州" />
      <textarea id="map-settings-desc"></textarea>
    `
    mapView._showSettingsModal()
    const handler = showModal.mock.calls[0][2][0].handler
    await expect(handler()).resolves.toBe(false)
    expect(toast).toHaveBeenCalledWith("更新失败：网络失败", "error")
  })

  it("_showSettingsModal 远端更新成功但页面对账失败时不把写入误报为失败", async () => {
    state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1", name: "九州" } }
    api.world.updateMap.mockResolvedValueOnce({ id: "m1", name: "新九州" })
    const reload = vi.spyOn(mapView, "_reloadMapStatePreservingSession")
      .mockRejectedValueOnce(new Error("列表暂不可用"))
    document.body.innerHTML = `
      <input id="map-settings-name" value="新九州" />
      <textarea id="map-settings-desc"></textarea>
    `
    mapView._showSettingsModal()

    await expect(showModal.mock.calls[0][2][0].handler()).resolves.toBe(true)
    expect(closeModal).toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("地图信息已更新", "success")
    expect(toast).toHaveBeenCalledWith("地图信息已更新，但页面对账失败：列表暂不可用", "warning")
    expect(toast).not.toHaveBeenCalledWith(expect.stringMatching(/^更新失败/), "error")
    reload.mockRestore()
  })

  it("保存设置后保留当前 mode（编辑模式）", async () => {
    globalThis.state.currentProjectId = "p1"
    mapState.mode = "edit"
    mapView._state = { map: { id: "m1", name: "九州", description: "古都" } }
    api.world.updateMap.mockResolvedValue({})
    api.world.getMapState.mockResolvedValue({
      map: { id: "m1", name: "新九州", description: "新描述", hex_size: 30, grid_width: 5, grid_height: 5 },
      breadcrumbs: [],
      tiles: [],
      location_bindings: [],
    })
    api.world.listMaps.mockResolvedValue({ items: [], total: 0 })
    document.body.innerHTML = `
      <input id="map-settings-name" value="新九州" />
      <textarea id="map-settings-desc">新描述</textarea>
      <div id="map-root"></div>
    `
    mapView._showSettingsModal()
    await showModal.mock.calls[0][2][0].handler()
    expect(mapState.mode).toBe("edit")
  })
})

describe("mapView 归档地图", () => {
  it("_renderList 显示归档按钮", () => {
    mapView._maps = [{ id: "m1", name: "九州", map_type: "world", grid_width: 30, grid_height: 20 }]
    const html = mapView._renderList()
    expect(html).toContain("data-action=\"map-delete\"")
    expect(html).toContain("归档")
  })

  it("_deleteMap 显示归档影响并包含转义后的地图名", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._maps = [{ id: "m1", name: "九州<img>", map_type: "world", grid_width: 30, grid_height: 20 }]
    api.world.getMapArchiveImpact.mockResolvedValue({ map_count: 3 })
    await mapView._deleteMap("m1")
    expect(confirmAction).toHaveBeenCalled()
    const message = confirmAction.mock.calls[0][0]
    expect(message).toContain("九州")
    expect(message).toContain("3 张地图")
    expect(message).not.toContain("<img")
  })

  it("_deleteMap 确认后归档子树并刷新列表", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._maps = [{ id: "m1", name: "九州", map_type: "world", grid_width: 30, grid_height: 20 }]
    api.world.getMapArchiveImpact.mockResolvedValue({ map_count: 1 })
    api.world.archiveMap.mockResolvedValue({})
    api.world.listMaps.mockResolvedValue({ items: [], total: 0 })
    await mapView._deleteMap("m1")
    const callback = confirmAction.mock.calls[0][1]
    await callback()
    expect(api.world.archiveMap).toHaveBeenCalledWith("m1", "p1")
    expect(api.world.listMaps).toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("地图子树已归档", "success")
  })

  it("_deleteMap 归档失败时 toast 错误", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._maps = [{ id: "m1", name: "九州", map_type: "world", grid_width: 30, grid_height: 20 }]
    api.world.getMapArchiveImpact.mockResolvedValue({ map_count: 1 })
    api.world.archiveMap.mockRejectedValue(new Error("网络失败"))
    await mapView._deleteMap("m1")
    const callback = confirmAction.mock.calls[0][1]
    await callback()
    expect(toast).toHaveBeenCalledWith("归档失败：网络失败", "error")
  })

  it("_deleteMap 归档最后一张地图后清空状态并回到列表", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._maps = [{ id: "m1", name: "九州", map_type: "world", grid_width: 30, grid_height: 20 }]
    mapView._state = {
      map: { id: "m1", name: "九州", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      location_bindings: [],
    }
    api.world.getMapArchiveImpact.mockResolvedValue({ map_count: 1 })
    api.world.archiveMap.mockResolvedValue({})
    api.world.listMaps.mockResolvedValue({ items: [], total: 0 })
    const unmountSpy = vi.spyOn(mapView, "unmount").mockImplementation(() => {
      mapView._state = null
      resetMapState()
    })
    const renderSpy = vi.spyOn(mapView, "_render").mockImplementation(() => {})

    await mapView._deleteMap("m1")
    const callback = confirmAction.mock.calls[0][1]
    await callback()

    expect(api.world.archiveMap).toHaveBeenCalledWith("m1", "p1")
    expect(unmountSpy).toHaveBeenCalled()
    expect(renderSpy).toHaveBeenCalledWith("map-root")
    expect(mapView._state).toBeNull()
    unmountSpy.mockRestore()
    renderSpy.mockRestore()
  })
})

describe("mapView Leaflet 事件清理", () => {
  it("_teardownInteractiveSurface 在 remove 之前 off 掉注册的 Leaflet 事件", () => {
    const offSpy = vi.fn(function () { return this })
    const removeSpy = vi.fn()
    mapView._leaflet = {
      off: offSpy,
      remove: removeSpy,
      closePopup: vi.fn(),
    }
    mapView._teardownInteractiveSurface()
    expect(offSpy).toHaveBeenCalledWith("resize zoom move")
    expect(offSpy).toHaveBeenCalledWith("zoomend moveend")
    expect(removeSpy).toHaveBeenCalled()
    expect(mapView._leaflet).toBeNull()
  })
})

describe("mapEditPanel 绑定计数", () => {
  it("updateBindingPendingCount 更新 DOM", () => {
    document.body.innerHTML = `<span id="map-binding-pending-count">0 个待绑定</span>`
    updateBindingPendingCount(3)
    expect(document.getElementById("map-binding-pending-count").textContent).toBe("3 个待绑定")
  })
})

describe("mapView 详情面板", () => {
  it("_renderDetailPanel 对中心绑定返回地点信息", () => {
    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      location_bindings: [{ hex_q: 1, hex_r: 1, location_entity_id: "loc1", is_center: true }],
    }
    mapView._maps = []
    mapView._locations = [{ id: "loc1", name: "洛阳", summary: "古都" }]
    const html = mapView._renderDetailPanel(1, 1)
    expect(html).toContain("洛阳")
    expect(html).toContain("古都")
    expect(html).toContain("创建详图")
  })

  it("_renderDetailPanel 使用索引缓存避免热路径数组扫描", () => {
    const bindings = [
      { hex_q: 1, hex_r: 1, location_entity_id: "loc1", is_center: true },
      { hex_q: 1, hex_r: 2, location_entity_id: "loc1", is_center: false },
    ]
    const locations = [{ id: "loc1", name: "洛阳", summary: "古都" }]
    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [{ hex_q: 1, hex_r: 1, terrain_type: "grassland" }],
      location_bindings: bindings,
    }
    mapView._maps = []
    mapView._locations = locations
    mapView._rebuildIndexes()
    mapView._state.location_bindings.find = () => {
      throw new Error("location_bindings.find should not be used after indexing")
    }
    mapView._state.location_bindings.filter = () => {
      throw new Error("location_bindings.filter should not be used for binding counts")
    }
    mapView._locations.find = () => {
      throw new Error("locations.find should not be used after indexing")
    }

    const html = mapView._renderDetailPanel(1, 1)

    expect(html).toContain("洛阳")
    expect(html).toContain("古都")
    expect(html).toContain(">2<")
  })

  it("地点与线路重叠时优先打开地点信息", () => {
    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      markers: [],
      territories: [],
      terrain_layers: [],
      terrain_patches: [],
      location_bindings: [{
        hex_q: 1, hex_r: 1, location_entity_id: "loc1", is_center: true,
      }],
    }
    mapView._pathState = {
      path_layers: [{ id: "layer-1", category: "transport" }],
      paths: [{
        id: "path-1",
        name: "重叠道路",
        path_layer_id: "layer-1",
        path_type: "street",
        nodes: [{ q: 0, r: 1 }, { q: 2, r: 1 }],
      }],
      nodes: [],
    }
    mapView._locations = [{ id: "loc1", name: "莫雷蒂家公寓", summary: "家" }]
    mapView._rebuildIndexes()

    const html = mapView._renderDetailPanel(1, 1)

    expect(mapView._typedSelectionAt(1, 1)).toMatchObject({
      kind: "location",
      entityId: "loc1",
    })
    expect(html).toContain("莫雷蒂家公寓")
    expect(html).not.toContain("重叠道路")
  })

  it("从线路标签显式打开线路时不被重叠地点详情覆盖", () => {
    document.body.innerHTML = `<div id="map-detail-panel"></div>`
    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      markers: [],
      territories: [],
      terrain_layers: [],
      terrain_patches: [],
      location_bindings: [{
        hex_q: 1, hex_r: 1, location_entity_id: "loc1", is_center: true,
      }],
    }
    mapView._pathState = {
      path_layers: [{ id: "layer-1", category: "transport" }],
      paths: [{
        id: "path-1",
        name: "重叠道路",
        path_layer_id: "layer-1",
        path_type: "street",
        nodes: [{ q: 0, r: 1 }, { q: 2, r: 1 }],
      }],
      nodes: [],
    }
    mapView._locations = [{ id: "loc1", name: "莫雷蒂家公寓", summary: "家" }]
    mapView._rebuildIndexes()

    expect(mapView._openMapLayoutItem({ kind: "path", id: "path-1", q: 1, r: 1 })).toBe(true)

    const panel = document.getElementById("map-detail-panel")
    expect(panel.textContent).toContain("重叠道路")
    expect(panel.textContent).not.toContain("莫雷蒂家公寓")
  })

  it("从标记和势力标签显式打开对象时不被重叠地点覆盖", () => {
    document.body.innerHTML = `<div id="map-detail-panel"></div>`
    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      markers: [{
        id: "marker-1", entity_id: "char-1", marker_type: "character",
        label: "克莱恩", hex_q: 1, hex_r: 1,
      }],
      territories: [{
        id: "territory-1", faction_entity_id: "faction-1", hex_q: 1, hex_r: 1,
      }],
      terrain_layers: [],
      terrain_patches: [],
      location_bindings: [{
        hex_q: 1, hex_r: 1, location_entity_id: "loc1", is_center: true,
      }],
    }
    mapView._locations = [{ id: "loc1", name: "莫雷蒂家公寓", summary: "家" }]
    mapView._allEntities = [{ id: "faction-1", name: "值夜者" }]
    mapView._rebuildIndexes()

    expect(mapView._openMapLayoutItem({
      kind: "marker", id: "marker-1", q: 1, r: 1,
    })).toBe(true)
    expect(document.getElementById("map-detail-panel").textContent).toContain("克莱恩")
    expect(document.getElementById("map-detail-panel").textContent).not.toContain("莫雷蒂家公寓")

    expect(mapView._openMapLayoutItem({
      kind: "territory", id: "faction-1", q: 1, r: 1,
    })).toBe(true)
    expect(document.getElementById("map-detail-panel").textContent).toContain("值夜者")
    expect(document.getElementById("map-detail-panel").textContent).not.toContain("莫雷蒂家公寓")
  })
})

describe("mapView tooltip", () => {
  const evil = `<img src=x onerror=alert(1)>`

  it.each([
    {
      name: "对中心绑定返回地点名",
      state: {
        map: { hex_size: 30, grid_width: 5, grid_height: 5 },
        tiles: [{ hex_q: 1, hex_r: 1, terrain_type: "grassland" }],
        location_bindings: [{ hex_q: 1, hex_r: 1, location_entity_id: "loc1", is_center: true }],
      },
      locations: [{ id: "loc1", name: "洛阳" }],
      q: 1,
      r: 1,
      contain: ["洛阳", "中心"],
    },
    {
      name: "对恶意地点名进行 XSS 转义",
      state: {
        map: { hex_size: 30, grid_width: 5, grid_height: 5 },
        tiles: [{ hex_q: 1, hex_r: 1, terrain_type: "grassland" }],
        location_bindings: [{ hex_q: 1, hex_r: 1, location_entity_id: "loc1", is_center: true }],
      },
      locations: [{ id: "loc1", name: evil }],
      q: 1,
      r: 1,
      contain: ["&lt;img"],
      notContain: ["<img"],
    },
    {
      name: "对非中心绑定不含中心标签",
      state: {
        map: { hex_size: 30, grid_width: 5, grid_height: 5 },
        tiles: [{ hex_q: 1, hex_r: 1, terrain_type: "forest" }],
        location_bindings: [{ hex_q: 1, hex_r: 1, location_entity_id: "loc1", is_center: false }],
      },
      locations: [{ id: "loc1", name: "洛阳" }],
      q: 1,
      r: 1,
      contain: ["洛阳"],
      notContain: ["中心"],
    },
    {
      name: "对无绑定格返回地形",
      state: {
        map: { hex_size: 30, grid_width: 5, grid_height: 5 },
        tiles: [{ hex_q: 2, hex_r: 2, terrain_type: "water" }],
        location_bindings: [],
      },
      locations: [],
      q: 2,
      r: 2,
      contain: ["water"],
    },
  ])("_buildTooltipContent $name", ({ state, locations, q, r, contain, notContain }) => {
    mapView._state = state
    mapView._locations = locations
    const html = mapView._buildTooltipContent(q, r)
    for (const text of contain) {
      expect(html).toContain(text)
    }
    for (const text of notContain || []) {
      expect(html).not.toContain(text)
    }
  })
})

describe("mapView 拖拽绘制", () => {
  beforeEach(() => {
    resetMapState()
  })

  it("_handleDragDraw brush 把新格加入 pending", () => {
    mapState.mode = "edit"
    mapState.activeTool = "brush"
    mapState.selectedTerrain = "water"
    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      location_bindings: [],
    }
    startDragDraw()
    mapView._handleDragDraw(1, 1)
    mapView._handleDragDraw(1, 2)
    expect(Object.keys(mapState.pendingTerrainChanges)).toHaveLength(2)
  })

  it("bucket 单击正常填充", () => {
    mapState.mode = "edit"
    mapState.activeTool = "bucket"
    mapState.selectedTerrain = "water"
    const tiles = []
    for (let q = 0; q < 3; q++) {
      for (let r = 0; r < 3; r++) {
        tiles.push({ hex_q: q, hex_r: r, terrain_type: "grassland" })
      }
    }
    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 3, grid_height: 3 },
      tiles,
      location_bindings: [],
    }
    mapView._handleBucketClick(0, 0)
    expect(Object.keys(mapState.pendingTerrainChanges)).toHaveLength(9)
    expect(mapState.pendingTerrainChanges["0,0"].terrain_type).toBe("water")
    expect(mapState.pendingTerrainChanges["2,2"].terrain_type).toBe("water")
  })

  it("bind 中心拖拽同步为唯一 layout 锚点", () => {
    mapState.mode = "edit"
    mapState.activeTool = "bind"
    mapState.selectedLocationEntityId = "loc1"
    mapState.bindCenterMode = true
    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      location_bindings: [],
    }
    startDragDraw()
    mapView._handleDragDraw(1, 1)
    mapView._handleDragDraw(1, 2)
    expect(mapState.pendingBindings).toEqual({})
    expect(mapState.pendingLocationLayouts.loc1).toMatchObject({
      location_entity_id: "loc1", center_hex_q: 1, center_hex_r: 2,
      layout_source: "binding_center_edit",
    })
  })

  it("bind 范围点击已有格会进入删除草稿而不是重复新增", () => {
    mapState.mode = "edit"
    mapState.editorLayer = "location"
    mapState.activeTool = "bind"
    mapState.selectedLocationEntityId = "loc1"
    mapState.bindCenterMode = false
    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      location_bindings: [{
        id: "binding-1",
        location_entity_id: "loc1",
        hex_q: 1,
        hex_r: 1,
        is_center: false,
      }],
    }
    startDragDraw()

    mapView._handleDragDraw(1, 1)

    expect(mapState.pendingBindings["1,1"]).toMatchObject({
      binding_id: "binding-1",
      operation: "delete",
    })
  })

  it("out-of-grid 不加入 pending", () => {
    mapState.mode = "edit"
    mapState.activeTool = "brush"
    mapState.selectedTerrain = "water"
    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 3, grid_height: 3 },
      tiles: [],
      location_bindings: [],
    }
    startDragDraw()
    mapView._handleDragDraw(-1, 0)
    mapView._handleDragDraw(0, 0)
    mapView._handleDragDraw(3, 3)
    expect(Object.keys(mapState.pendingTerrainChanges)).toHaveLength(1)
    expect(mapState.pendingTerrainChanges["0,0"]).toBeDefined()
  })
})

describe("mapView 批量绑定保存", () => {
  it("_applyBindings 批量提交 pending 绑定", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1" } }
    api.world.createLocationBindings.mockResolvedValue({})
    mapState.pendingBindings = {
      "1,2": { location_entity_id: "loc1", hex_q: 1, hex_r: 2, is_center: false },
      "1,3": { location_entity_id: "loc1", hex_q: 1, hex_r: 3, is_center: true },
    }
    await mapView._applyBindings()
    expect(api.world.createLocationBindings).toHaveBeenCalledWith(
      "m1",
      {
        location_entity_id: "loc1",
        hexes: expect.arrayContaining([
          { hex_q: 1, hex_r: 2, is_center: false },
          { hex_q: 1, hex_r: 3, is_center: true },
        ]),
      },
      "p1"
    )
    expect(mapState.pendingBindings).toEqual({})
  })

  it("_applyBindings 删除已有范围格", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1" } }
    api.world.deleteLocationBinding.mockResolvedValue(undefined)
    mapState.pendingBindings = {
      "1,2": {
        location_entity_id: "loc1",
        hex_q: 1,
        hex_r: 2,
        operation: "delete",
        binding_id: "binding-1",
      },
    }

    await mapView._applyBindings()

    expect(api.world.deleteLocationBinding).toHaveBeenCalledWith(
      "m1", "binding-1", "p1",
    )
    expect(api.world.createLocationBindings).not.toHaveBeenCalled()
  })

  it("_applyBindings 空 pending 直接返回", async () => {
    mapState.pendingBindings = {}
    await mapView._applyBindings()
    expect(api.world.createLocationBindings).not.toHaveBeenCalled()
  })

  it("_applyAllChanges 应用失败时保留 pending", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1" } }
    api.world.batchUpdateTiles.mockRejectedValue(new Error("网络失败"))
    stageTerrainChange(1, 1, "water")
    stageBindingChange("loc1", 2, 2, false)
    await mapView._applyAllChanges()
    expect(mapState.pendingTerrainChanges["1,1"]).toBeDefined()
    expect(mapState.pendingBindings["2,2"]).toBeDefined()
  })

  it("_applyTerrainChanges 失败时恢复 pending 和 undoStack", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1" } }
    api.world.batchUpdateTiles.mockRejectedValue(new Error("保存失败"))
    stageTerrainChange(1, 1, "water", 3)
    await expect(mapView._applyTerrainChanges()).rejects.toThrow("保存失败")
    expect(mapState.undoStack).toHaveLength(0)
    expect(mapState.pendingTerrainChanges["1,1"]).toMatchObject({
      hex_q: 1, hex_r: 1, terrain_type: "water", elevation: 3,
    })
  })

  it("_applyTerrainChanges 在服务批次上限前保留 pending", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1" } }
    mapState.pendingTerrainChanges = Object.fromEntries(
      Array.from({ length: 10001 }, (_, index) => [
        `${index},0`,
        { hex_q: index, hex_r: 0, terrain_type: "water" },
      ]),
    )

    await expect(mapView._applyTerrainChanges()).rejects.toThrow("单次最多应用 10000 个地形变更")
    expect(api.world.batchUpdateTiles).not.toHaveBeenCalled()
    expect(Object.keys(mapState.pendingTerrainChanges)).toHaveLength(10001)
  })

  it("_applyBindings 在单地点绑定上限前保留 pending", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1" } }
    mapState.pendingBindings = Object.fromEntries(
      Array.from({ length: 5001 }, (_, index) => [
        `${index},0`,
        { location_entity_id: "loc1", hex_q: index, hex_r: 0, is_center: false },
      ]),
    )

    await expect(mapView._applyBindings()).rejects.toThrow("单个地点单次最多绑定 5000 个地图格")
    expect(api.world.createLocationBindings).not.toHaveBeenCalled()
    expect(Object.keys(mapState.pendingBindings)).toHaveLength(5001)
  })

})

describe("mapView 领地分层草稿", () => {
  it("连续绘制先进入草稿，保存时按组织批量提交", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1" }, territories: [] }
    mapState.selectedFactionId = "f1"
    mapState.territoryEraseMode = false

    mapView._handleTerritoryEdit(1, 2)
    mapView._handleTerritoryEdit(2, 2)

    expect(api.world.createTerritories).not.toHaveBeenCalled()
    expect(Object.keys(mapState.pendingTerritoryChanges.add)).toHaveLength(2)

    api.world.createTerritories.mockResolvedValue([])
    await mapView._applyTerritoryChanges()

    expect(api.world.createTerritories).toHaveBeenCalledWith(
      "m1",
      {
        faction_entity_id: "f1",
        hexes: expect.arrayContaining([
          { hex_q: 1, hex_r: 2 },
          { hex_q: 2, hex_r: 2 },
        ]),
      },
      "p1",
    )
    expect(mapState.pendingTerritoryChanges).toEqual({ add: {}, remove: {} })
  })

  it("擦除持久化领地先进入待删除草稿", () => {
    mapView._state = {
      map: { id: "m1" },
      territories: [{ id: "t1", faction_entity_id: "f1", hex_q: 3, hex_r: 4 }],
    }
    mapState.selectedFactionId = "f1"
    mapState.territoryEraseMode = true

    mapView._handleTerritoryEdit(3, 4)

    expect(mapState.pendingTerritoryChanges.remove.t1).toMatchObject({ id: "t1" })
    expect(mapView._effectiveTerritories()).toEqual([])
    expect(api.world.deleteMapTerritory).not.toHaveBeenCalled()
  })
})

describe("mapView 覆盖图层草稿保护", () => {
  it("只切换素材也会形成可撤销草稿，且未应用时不能切层", () => {
    mapState.mode = "edit"
    mapState.editorLayer = "terrainOverlay"
    mapState.selectedTerrainLayerId = "layer-1"
    mapState.selectedTerrainAssetKey = "forest"
    mapView._state = {
      map: { id: "m1", grid_width: 8, grid_height: 8 },
      terrain_layers: [
        { id: "layer-1", name: "森林", terrain_asset_key: "forest", meta: {}, locked: false },
        { id: "layer-2", name: "道路", terrain_asset_key: "road", meta: {}, locked: false },
      ],
      terrain_regions: [],
      terrain_patches: [],
    }
    document.body.innerHTML = `<main id="workspace-content">${renderEditPanel({
      terrainLayers: mapView._state.terrain_layers,
    })}</main>`
    mapView._bindMapEvents()
    const asset = document.getElementById("map-overlay-asset")
    asset.value = "road"

    asset.dispatchEvent(new Event("change"))

    expect(mapState.pendingTerrainOverlay.layerUpdate.terrain_asset_key).toBe("road")
    expect(mapState.editorHistory.terrainOverlay).toHaveLength(1)
    const layer = document.getElementById("map-overlay-layer")
    layer.value = "layer-2"
    layer.dispatchEvent(new Event("change"))
    expect(mapState.selectedTerrainLayerId).toBe("layer-1")
    expect(layer.value).toBe("layer-1")
    expect(toast).toHaveBeenCalledWith(
      "当前覆盖图层有未应用修改，请先应用或撤销后再切换",
      "warning",
    )
    mapView.unmount()
  })
})

describe("mapView 编辑生命周期", () => {
  it("在进入编辑的异步加载期间 unmount 不会复活编辑态", async () => {
    mapView._state = { map: { id: "m1" } }
    const onEditingChange = vi.fn()
    mapView._mountContext = { onEditingChange }
    let releaseLocations
    const locations = vi.spyOn(mapView, "_loadLocations").mockImplementation(
      () => new Promise((resolve) => { releaseLocations = resolve }),
    )
    const entities = vi.spyOn(mapView, "_loadAllEntities").mockResolvedValue()
    const tree = vi.spyOn(mapView, "_loadLayerTree").mockResolvedValue()
    const paths = vi.spyOn(mapView, "_loadPaths").mockResolvedValue()
    const render = vi.spyOn(mapView, "_render").mockImplementation(() => {})

    const pending = mapView._enterEdit()
    await vi.waitFor(() => expect(releaseLocations).toBeTypeOf("function"))
    mapView.unmount()
    releaseLocations()

    await expect(pending).resolves.toBe(false)
    expect(mapState.mode).toBe("browse")
    expect(onEditingChange).not.toHaveBeenCalled()
    expect(render).not.toHaveBeenCalled()
    locations.mockRestore()
    entities.mockRestore()
    tree.mockRestore()
    paths.mockRestore()
    render.mockRestore()
  })

  it("保存等待期间 unmount 后不重新渲染或发送过期成功提示", async () => {
    mapView._state = { map: { id: "m1" } }
    mapView._mountContext = { mapId: "m1" }
    mapState.mode = "edit"
    let releaseApply
    const apply = vi.spyOn(mapView, "_applyAllChanges").mockImplementation(
      () => new Promise((resolve) => { releaseApply = resolve }),
    )
    const render = vi.spyOn(mapView, "_render").mockImplementation(() => {})

    const pending = mapView._saveAndExit()
    await vi.waitFor(() => expect(releaseApply).toBeTypeOf("function"))
    mapView.unmount()
    releaseApply(true)

    await expect(pending).resolves.toBe(true)
    expect(mapState.mode).toBe("browse")
    expect(render).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalledWith("已保存", "success")
    apply.mockRestore()
    render.mockRestore()
  })

  it("应用到状态重载完成期间锁定工作区并拒绝二次提交", async () => {
    document.body.append(renderHtml(`
      <div id="map-root"><button>应用</button></div>
      <div id="modal-overlay"><button>确认</button></div>
    `))
    state.currentProjectId = "p1"
    mapView._mountRootId = "map-root"
    mapView._state = {
      map: { id: "m1", editor_revision: 1 },
      markers: [],
      territories: [],
    }
    mapState.mode = "edit"
    mapState.editorLayer = "marker"
    mapState.pendingMarkerChanges = {
      marker1: { operation: "update", id: "marker1", data: { label: "新标签" } },
    }
    let releaseApply
    let releaseReload
    api.world.applyMapEditor.mockImplementation(() => new Promise((resolve) => {
      releaseApply = resolve
    }))
    const reload = vi.spyOn(mapView, "_reloadMapStatePreservingSession")
      .mockImplementation(() => new Promise((resolve) => {
        releaseReload = resolve
      }))
    const tree = vi.spyOn(mapView, "_loadLayerTree").mockResolvedValue()
    const paths = vi.spyOn(mapView, "_loadPaths").mockResolvedValue()
    const rerender = vi.spyOn(mapView, "_rerenderEditor").mockImplementation(() => {})

    const first = mapView._applyAllChanges({ onlyLayer: true })
    await vi.waitFor(() => expect(releaseApply).toBeTypeOf("function"))

    expect(document.getElementById("map-root").inert).toBe(true)
    expect(document.getElementById("map-root").getAttribute("aria-busy")).toBe("true")
    expect(document.getElementById("modal-overlay").inert).toBe(true)
    expect(mapView.canLeave()).toBe(false)
    await expect(mapView._applyAllChanges({ onlyLayer: true })).resolves.toBe(false)
    expect(api.world.applyMapEditor).toHaveBeenCalledTimes(1)

    releaseApply({ editor_revision: 2, client_id_map: {} })
    await vi.waitFor(() => expect(releaseReload).toBeTypeOf("function"))
    expect(document.getElementById("map-root").inert).toBe(true)
    expect(document.getElementById("map-root").getAttribute("aria-busy")).toBe("true")
    releaseReload(true)
    await expect(first).resolves.toBe(true)
    expect(document.getElementById("map-root").inert).toBe(false)
    expect(document.getElementById("map-root").hasAttribute("aria-busy")).toBe(false)
    expect(document.getElementById("modal-overlay").inert).toBe(false)

    reload.mockRestore()
    tree.mockRestore()
    paths.mockRestore()
    rerender.mockRestore()
  })

  it("重载在替换服务端状态前抓取最新草稿而不是请求发出时的旧快照", async () => {
    state.currentProjectId = "p1"
    mapView._mountContext = { mapId: "m1" }
    mapView._state = {
      map: { id: "m1", editor_revision: 1, grid_width: 10, grid_height: 10 },
      markers: [{ id: "marker1", label: "请求前" }],
      location_bindings: [],
      location_layouts: [],
      tiles: [],
      territories: [],
    }
    mapState.editorLayer = "marker"
    mapState.pendingMarkerChanges = {
      marker1: { operation: "update", id: "marker1", data: { label: "请求前" } },
    }
    let releaseState
    api.world.getMapState.mockImplementation(() => new Promise((resolve) => {
      releaseState = resolve
    }))

    const pending = mapView._reloadMapStatePreservingSession("m1")
    await vi.waitFor(() => expect(releaseState).toBeTypeOf("function"))
    mapState.pendingMarkerChanges.marker1.data.label = "请求期间的最新草稿"
    mapView._state.markers[0].label = "请求期间的最新草稿"
    releaseState({
      map: { id: "m1", editor_revision: 2, grid_width: 10, grid_height: 10 },
      markers: [{ id: "marker1", label: "远端版本" }],
      location_bindings: [],
      location_layouts: [],
      tiles: [],
      territories: [],
    })

    await expect(pending).resolves.toBe(true)
    expect(mapState.pendingMarkerChanges.marker1.data.label)
      .toBe("请求期间的最新草稿")
    expect(mapView._state.markers[0].label).toBe("请求期间的最新草稿")
  })

  it("保存全部后若仍有草稿则不退出编辑态", async () => {
    mapView._state = { map: { id: "m1" } }
    mapState.mode = "edit"
    mapState.pendingMarkerChanges = {
      marker1: { operation: "update", id: "marker1", data: { label: "尚未保存" } },
    }
    const apply = vi.spyOn(mapView, "_applyAllChanges").mockResolvedValue(true)
    const render = vi.spyOn(mapView, "_render").mockImplementation(() => {})

    await expect(mapView._saveAndExit()).resolves.toBe(false)
    expect(mapState.mode).toBe("edit")
    expect(render).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(
      "仍有未保存的地图草稿，请再次应用后再退出",
      "warning",
    )

    apply.mockRestore()
    render.mockRestore()
  })

  it("旧地图的延迟图层树响应不会覆盖新 mount", async () => {
    state.currentProjectId = "p1"
    mapView._state = { map: { id: "m1" } }
    mapView._mountContext = { mapId: "m1" }
    let resolveTree
    api.world.getMapLayerTree.mockImplementation(() => new Promise((resolve) => {
      resolveTree = resolve
    }))

    const pending = mapView._loadLayerTree()
    await vi.waitFor(() => expect(resolveTree).toBeTypeOf("function"))
    mapView.unmount()
    mapView._state = { map: { id: "m2" } }
    mapView._mountContext = { mapId: "m2" }
    mapView._layerTree = { nodes: [{ id: "new-tree" }] }
    resolveTree({ nodes: [{ id: "old-tree" }] })

    await expect(pending).resolves.toBe(false)
    expect(mapView._layerTree).toEqual({ nodes: [{ id: "new-tree" }] })
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("图层树加载失败"), "warning")
  })
})

describe("mapView 撤销", () => {
  it("_undo 清空 pending 地形变更", () => {
    stageTerrainChange(1, 1, "water")
    stageTerrainChange(2, 2, "forest")
    mapView._undo()
    expect(mapState.pendingTerrainChanges).toEqual({})
    expect(toast).toHaveBeenCalledWith("已撤销 2 个地形变更", "info")
  })

  it("_undo 优先清空 pending 绑定变更", () => {
    stageTerrainChange(1, 1, "water")
    stageBindingChange("loc1", 2, 2, false)
    mapView._undo()
    expect(mapState.pendingBindings).toEqual({})
    expect(mapState.pendingTerrainChanges["1,1"]).toBeDefined()
  })

  it("_undo 无 pending 时提示", () => {
    mapView._undo()
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("无可撤销的操作"), "info")
  })
})

describe("mapHexRenderer 标记绘制", () => {
  it.each([
    {
      name: "绘制可见标记",
      markers: [{ hex_q: 1, hex_r: 1, marker_type: "character", label: "张三", visible: true, offset_x: 0, offset_y: 0 }],
      expectArc: true,
      expectFill: true,
    },
    {
      name: "过滤不可见标记",
      markers: [{ hex_q: 1, hex_r: 1, marker_type: "character", visible: false, offset_x: 0, offset_y: 0 }],
      expectArc: false,
    },
    {
      name: "空数组不绘制",
      markers: [],
      expectBeginPath: false,
    },
    {
      name: "不同类型使用不同颜色",
      markers: [
        { hex_q: 1, hex_r: 1, marker_type: "event", visible: true, offset_x: 0, offset_y: 0 },
        { hex_q: 2, hex_r: 2, marker_type: "item", visible: true, offset_x: 0, offset_y: 0 },
      ],
      expectArcTimes: 2,
    },
  ])("drawMarkers $name", ({ markers, expectArc, expectFill, expectBeginPath, expectArcTimes }) => {
    const ctx = createCanvasMock()
    drawMarkers(ctx, markers, 30, 0, 0, null)
    if (expectArcTimes !== undefined) expect(ctx.arc).toHaveBeenCalledTimes(expectArcTimes)
    if (expectArc === true) expect(ctx.arc).toHaveBeenCalled()
    if (expectArc === false) expect(ctx.arc).not.toHaveBeenCalled()
    if (expectFill === true) expect(ctx.fill).toHaveBeenCalled()
    if (expectBeginPath === false) expect(ctx.beginPath).not.toHaveBeenCalled()
  })
})
