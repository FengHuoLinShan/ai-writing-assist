/**
 * 地图视图测试 — PRD docs/PRD-动态地图功能.md
 *
 * 覆盖：
 * - mapHexRenderer 几何算法（hexToPixel/pixelToHex 往返、邻居、floodFill、hexRound）
 * - mapState 状态机（stage/consume/undo、reset）
 * - mapView 列表渲染（空列表、有地图列表、XSS 转义）
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import {
  hexToPixel,
  pixelToHex,
  hexRound,
  getNeighbors,
  floodFillTerrain,
  TERRAIN_COLORS,
  TERRAIN_OPTIONS,
  hexCorners,
  drawPendingTerrain,
  drawPendingBindings,
  drawHoverHighlight,
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
} from "../views/mapState.js"
import mapView from "../views/mapView.js"
import renderEditPanel, { updatePendingCount, updateBindingPendingCount, toggleToolSections } from "../views/mapEditPanel.js"

beforeEach(() => {
  // 防御：单文件运行时 setup.js 可能未在同一 worker 执行，兜底初始化全局
  if (!globalThis.state) {
    globalThis.state = { currentProjectId: null, currentSubView: null }
  }
  globalThis.state.currentProjectId = null
  if (globalThis.api) vi.clearAllMocks()
  resetMapState()
  if (typeof document !== "undefined") document.body.innerHTML = ""
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

  describe("mapHexRenderer 绘制辅助", () => {
    it("drawPendingTerrain 绘制 pending 格", () => {
      const ctx = {
        beginPath: vi.fn(),
        moveTo: vi.fn(),
        lineTo: vi.fn(),
        closePath: vi.fn(),
        fill: vi.fn(),
        stroke: vi.fn(),
        save: vi.fn(),
        restore: vi.fn(),
        set globalAlpha(value) {},
      }
      drawPendingTerrain(ctx, [{ hex_q: 0, hex_r: 0, terrain_type: "water" }], 30, 0, 0)
      expect(ctx.beginPath).toHaveBeenCalled()
      expect(ctx.fill).toHaveBeenCalled()
    })

    it("drawPendingBindings 绘制 pending 地点绑定", () => {
      const ctx = {
        beginPath: vi.fn(),
        moveTo: vi.fn(),
        lineTo: vi.fn(),
        closePath: vi.fn(),
        stroke: vi.fn(),
        fill: vi.fn(),
        fillText: vi.fn(),
        save: vi.fn(),
        restore: vi.fn(),
        setLineDash: vi.fn(),
        set globalAlpha(value) {},
      }
      drawPendingBindings(ctx, [{ hex_q: 0, hex_r: 0, is_center: true }], 30, 0, 0)
      expect(ctx.beginPath).toHaveBeenCalled()
      expect(ctx.stroke).toHaveBeenCalled()
    })

    it("drawHoverHighlight 绘制悬停描边", () => {
      const ctx = {
        beginPath: vi.fn(),
        moveTo: vi.fn(),
        lineTo: vi.fn(),
        closePath: vi.fn(),
        stroke: vi.fn(),
      }
      drawHoverHighlight(ctx, 1, 1, 30, 0, 0)
      expect(ctx.stroke).toHaveBeenCalled()
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

describe("mapEditPanel 绑定计数", () => {
  it("updateBindingPendingCount 更新 DOM", () => {
    document.body.innerHTML = `<span id="map-binding-pending-count">0 个待绑定</span>`
    updateBindingPendingCount(3)
    expect(document.getElementById("map-binding-pending-count").textContent).toBe("3 个待绑定")
  })
})
