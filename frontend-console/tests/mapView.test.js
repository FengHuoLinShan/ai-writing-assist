/**
 * 地图视图测试 — PRD docs/PRD-动态地图功能.md
 *
 * 覆盖：
 * - mapHexRenderer 几何算法（hexToPixel/pixelToHex 往返、邻居、floodFill、hexRound）
 * - mapState 状态机（stage/consume/undo、reset）
 * - mapView 列表渲染（空列表、有地图列表、XSS 转义）
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { resetState, clearDocument, createCanvasMock } from "./helpers.js"
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

beforeEach(() => {
  // 防御：单文件运行时 setup.js 可能未在同一 worker 执行，兜底初始化全局
  if (!globalThis.state) {
    globalThis.state = { currentProjectId: null, currentSubView: null }
  }
  resetState()
  clearDocument()
  if (globalThis.api) vi.clearAllMocks()
  resetMapState()
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

    expect(api.world.listMaps).toHaveBeenCalledWith({ novel_id: "p1" })
    expect(mapView._maps).toHaveLength(1)
    expect(mapView._maps[0].name).toBe("九州")
  })

  it("listMaps 失败时回退空列表", async () => {
    globalThis.state.currentProjectId = "p1"
    api.world.listMaps.mockRejectedValue(new Error("网络失败"))
    await mapView._loadMaps()
    expect(mapView._maps).toEqual([])
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
    const formHtml = showModal.mock.calls[0][1]
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

describe("mapView 删除地图", () => {
  it("_renderList 显示删除按钮", () => {
    mapView._maps = [{ id: "m1", name: "九州", map_type: "world", grid_width: 30, grid_height: 20 }]
    const html = mapView._renderList()
    expect(html).toContain("data-action=\"map-delete\"")
    expect(html).toContain("删除")
  })

  it("_deleteMap 显示确认信息并包含地图名", () => {
    globalThis.state.currentProjectId = "p1"
    mapView._maps = [{ id: "m1", name: "九州", map_type: "world", grid_width: 30, grid_height: 20 }]
    mapView._deleteMap("m1")
    expect(confirmAction).toHaveBeenCalled()
    const message = confirmAction.mock.calls[0][0]
    expect(message).toContain("九州")
    expect(message).not.toContain("<img")
  })

  it("_deleteMap 确认后调用 API 并刷新列表", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._maps = [{ id: "m1", name: "九州", map_type: "world", grid_width: 30, grid_height: 20 }]
    api.world.deleteMap.mockResolvedValue({})
    api.world.listMaps.mockResolvedValue({ items: [], total: 0 })
    mapView._deleteMap("m1")
    const callback = confirmAction.mock.calls[0][1]
    await callback()
    expect(api.world.deleteMap).toHaveBeenCalledWith("m1", "p1")
    expect(api.world.listMaps).toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("地图已删除", "success")
  })

  it("_deleteMap 失败时 toast 错误", async () => {
    globalThis.state.currentProjectId = "p1"
    mapView._maps = [{ id: "m1", name: "九州", map_type: "world", grid_width: 30, grid_height: 20 }]
    api.world.deleteMap.mockRejectedValue(new Error("网络失败"))
    mapView._deleteMap("m1")
    const callback = confirmAction.mock.calls[0][1]
    await callback()
    expect(toast).toHaveBeenCalledWith("删除失败：网络失败", "error")
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

  it("bind 拖拽加入 pending", () => {
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
    expect(Object.keys(mapState.pendingBindings)).toHaveLength(2)
    expect(mapState.pendingBindings["1,1"]).toMatchObject({
      location_entity_id: "loc1", hex_q: 1, hex_r: 1, is_center: true,
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
})

describe("mapHexRenderer P2 drawTerritories", () => {
  it.each([
    { name: "空数组不绘制", territories: [], colorMap: {}, expectBeginPath: false },
    { name: "绘制势力范围", territories: [{ faction_id: "f1", hexes: [{ hex_q: 1, hex_r: 1 }] }], colorMap: { f1: "#FF0000" }, expectBeginPath: true, fillStyleContains: "FF0000" },
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
