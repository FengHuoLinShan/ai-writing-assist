/**
 * 地图视图测试 — PRD docs/PRD-动态地图功能.md
 *
 * 覆盖：
 * - mapHexRenderer 几何算法（hexToPixel/pixelToHex 往返、邻居、floodFill、hexRound）
 * - mapState 状态机（stage/consume/undo、reset）
 * - mapView 列表渲染（空列表、有地图列表、XSS 转义）
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { resetState, clearDocument, createCanvasMock, renderHtml, autoConfirm } from "./helpers.js"
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
  resetState()
  clearDocument()
  if (globalThis.api) vi.clearAllMocks()
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
  mapView._setEditorApplyBusy(false)
  document.getElementById("leaflet-css-dynamic")?.remove()
  document.getElementById("leaflet-js-dynamic")?.remove()
  delete window.L
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
    const resources = interceptLeafletResourceAppend()
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

    window.L = {
      CRS: { Simple: {} },
      map: vi.fn(() => ({
        fitBounds: vi.fn(),
        on: vi.fn(),
        off: vi.fn(function () { return this }),
        getZoom: vi.fn(() => 0),
        latLngToContainerPoint: vi.fn(() => ({ x: 24, y: 36 })),
        eachLayer: vi.fn(),
        removeLayer: vi.fn(),
        getContainer: vi.fn(() => container),
        remove: vi.fn(),
      })),
      latLngBounds: vi.fn((bounds) => bounds),
    }

    mapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      location_bindings: [],
      markers: [],
      territories: [],
    }

    try {
      await mapView._initLeaflet()

      expect(mapView._canvas?.parentElement).toBe(container)
      expect(overlayPane.contains(mapView._canvas)).toBe(false)
    } finally {
      mapView._teardownInteractiveSurface()
      mapView._state = null
      HTMLCanvasElement.prototype.getContext = originalGetContext
      resources.restore()
      delete window.L
    }
  })

  it("loads Leaflet CSS and JS on demand when window.L is absent", async () => {
    const freshMapView = await importFreshMapView()
    const resources = interceptLeafletResourceAppend()
    const container = document.createElement("div")
    container.id = "map-leaflet"
    Object.defineProperty(container, "clientWidth", { value: 640, configurable: true })
    Object.defineProperty(container, "clientHeight", { value: 420, configurable: true })
    document.body.appendChild(container)

    const originalGetContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = vi.fn(() => createCanvasMock({
      methods: ["setTransform", "clearRect", "translate", "scale"],
    }))
    const leafletMap = {
      fitBounds: vi.fn(),
      on: vi.fn(),
      off: vi.fn(function () { return this }),
      getZoom: vi.fn(() => 0),
      latLngToContainerPoint: vi.fn(() => ({ x: 24, y: 36 })),
      eachLayer: vi.fn(),
      removeLayer: vi.fn(),
      getContainer: vi.fn(() => container),
      remove: vi.fn(),
    }
    freshMapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      location_bindings: [],
      markers: [],
      territories: [],
    }

    try {
      const init = freshMapView._initLeaflet()
      const link = document.getElementById("leaflet-css-dynamic")
      const script = document.getElementById("leaflet-js-dynamic")

      expect(link?.getAttribute("href")).toBe("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css")
      expect(script?.getAttribute("src")).toBe("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js")
      expect(script?.getAttribute("integrity")).toBe("sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=")

      window.L = {
        CRS: { Simple: {} },
        map: vi.fn(() => leafletMap),
        latLngBounds: vi.fn((bounds) => bounds),
      }
      script.onload()
      await init

      expect(window.L.map).toHaveBeenCalledWith(container, expect.objectContaining({
        crs: window.L.CRS.Simple,
        attributionControl: false,
      }))
      expect(freshMapView._leaflet).toBe(leafletMap)
    } finally {
      freshMapView._teardownInteractiveSurface()
      freshMapView._state = null
      HTMLCanvasElement.prototype.getContext = originalGetContext
      resources.restore()
      delete window.L
    }
  })

  it("reuses the in-flight Leaflet loader and does not inject duplicate resources", async () => {
    const freshMapView = await importFreshMapView()
    const resources = interceptLeafletResourceAppend()
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

    try {
      const first = freshMapView._initLeaflet()
      const second = freshMapView._initLeaflet()
      expect(resources.appended.filter((node) => node.id === "leaflet-css-dynamic")).toHaveLength(1)
      expect(resources.appended.filter((node) => node.id === "leaflet-js-dynamic")).toHaveLength(1)

      const script = document.getElementById("leaflet-js-dynamic")
      window.L = {
        CRS: { Simple: {} },
        map: vi.fn(() => ({
          fitBounds: vi.fn(),
          on: vi.fn(),
          off: vi.fn(function () { return this }),
          getZoom: vi.fn(() => 0),
          latLngToContainerPoint: vi.fn(() => ({ x: 24, y: 36 })),
          eachLayer: vi.fn(),
          removeLayer: vi.fn(),
          getContainer: vi.fn(() => container),
          remove: vi.fn(),
        })),
        latLngBounds: vi.fn((bounds) => bounds),
      }
      script.onload()
      await Promise.all([first, second])

      expect(window.L.map).toHaveBeenCalledTimes(1)
    } finally {
      freshMapView._teardownInteractiveSurface()
      freshMapView._state = null
      HTMLCanvasElement.prototype.getContext = originalGetContext
      resources.restore()
      delete window.L
    }
  })

  it("renders the existing failure state when Leaflet cannot load", async () => {
    const freshMapView = await importFreshMapView()
    const resources = interceptLeafletResourceAppend()
    const container = document.createElement("div")
    container.id = "map-leaflet"
    document.body.appendChild(container)
    freshMapView._state = {
      map: { id: "m1", hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [],
      location_bindings: [],
      markers: [],
      territories: [],
    }

    const init = freshMapView._initLeaflet()
    const script = document.getElementById("leaflet-js-dynamic")
    script.onerror()
    await init

    expect(container.textContent).toContain("地图引擎加载失败")
    expect(freshMapView._leaflet).toBeNull()
    resources.restore()
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
  })

  it("_showSettingsModal 保存时空名称给出警告", async () => {
    mapView._state = { map: { id: "m1", name: "九州" } }
    document.body.innerHTML = `
      <input id="map-settings-name" value="" />
      <textarea id="map-settings-desc"></textarea>
    `
    mapView._showSettingsModal()
    const handler = showModal.mock.calls[0][2][0].handler
    await handler()
    expect(toast).toHaveBeenCalledWith("请输入地图名称", "warning")
    expect(api.world.updateMap).not.toHaveBeenCalled()
  })

  it("_showSettingsModal 保存成功调用 updateMap 并重载", async () => {
    globalThis.state.currentProjectId = "p1"
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
    await handler()
    expect(toast).toHaveBeenCalledWith("更新失败：网络失败", "error")
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
      ],
    }

    expect(mapView._filteredMarkers().map((m) => m.id)).toEqual(["mk1"])
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
    vi.spyOn(mapView, "_loadMaps").mockResolvedValue()
    vi.spyOn(mapView, "_render").mockImplementation(() => {})
    autoConfirm()

    await mapView._runMapBulkAction("delete-maps")

    await vi.waitFor(() => {
      expect(api.world.archiveMap).toHaveBeenCalledWith("m1", "p1")
      expect(api.world.archiveMap).toHaveBeenCalledWith("m2", "p1")
      expect(toast).toHaveBeenCalledWith(expect.stringContaining("成功 2 / 2"), "success")
    })
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
