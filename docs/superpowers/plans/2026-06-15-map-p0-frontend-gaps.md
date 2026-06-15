# 动态地图 P0 前端偏差修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 PRD `docs/PRD-动态地图功能.md` 文末列出的 7 个 P0 前端已知偏差，使地图浏览与编辑体验闭环。

**Architecture:** 先扩展 `mapState.js` 统一承载 pending/drag/hover/selected 状态，再扩展 `mapHexRenderer.js` 负责绘制，最后集中修改 `mapView.js` 的渲染与事件处理。所有动态文本通过 `esc()` 安全处理；tooltip 使用 Leaflet popup；批量绑定保存通过现有 `createLocationBindings` API。

**Tech Stack:** vanilla JS SPA, Leaflet 1.9.4 (CDN), Canvas 2D, Vitest。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `frontend-console/views/mapState.js` | 扩展会话状态：pendingBindings、dragDrawing、hoveredHex、selectedHex 及纯函数。 |
| `frontend-console/views/mapHexRenderer.js` | 新增 pending 地形/绑定、悬停高亮的绘制函数。 |
| `frontend-console/views/mapEditPanel.js` | 在编辑面板显示 pending 绑定计数。 |
| `frontend-console/views/mapView.js` | 渲染详情面板、tooltip、拖拽绘制、批量绑定保存、删除/设置 UI。 |
| `frontend-console/styles.css` | 右侧面板、pending 样式、设置 modal 样式。 |
| `frontend-console/tests/mapView.test.js` | 补充状态、渲染、交互测试。 |

---

## Task 1: 扩展 mapState.js 状态层

**Files:**
- Modify: `frontend-console/views/mapState.js`
- Test: `frontend-console/tests/mapView.test.js`

- [ ] **Step 1: 写 failing test**

在 `frontend-console/tests/mapView.test.js` 的 `mapState 状态机` describe 下新增：

```javascript
import {
  // ... 已有 import ...
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

// ... 已有测试 ...

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
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "stageBindingChange"
```

Expected: FAIL, imports not found.

- [ ] **Step 3: 实现 mapState 扩展**

修改 `frontend-console/views/mapState.js`，在原有对象和函数基础上追加：

```javascript
export const mapState = {
  // ... 原有字段 ...
  pendingBindings: {},
  dragDrawing: false,
  lastDragHex: null,
  hoveredHex: null,
  selectedHex: null,
  bindCenterMode: false,
}

export function resetMapState() {
  // ... 原有清空 ...
  mapState.pendingBindings = {}
  mapState.dragDrawing = false
  mapState.lastDragHex = null
  mapState.hoveredHex = null
  mapState.selectedHex = null
  mapState.bindCenterMode = false
}

export function stageBindingChange(entityId, q, r, isCenter) {
  const key = `${q},${r}`
  if (mapState.pendingBindings[key] &&
      mapState.pendingBindings[key].location_entity_id === entityId &&
      mapState.pendingBindings[key].is_center === isCenter) {
    delete mapState.pendingBindings[key]
    return
  }
  mapState.pendingBindings[key] = {
    location_entity_id: entityId,
    hex_q: q,
    hex_r: r,
    is_center: isCenter,
  }
}

export function consumePendingBindings() {
  const bindings = Object.values(mapState.pendingBindings)
  mapState.pendingBindings = {}
  return bindings
}

export function setHoveredHex(q, r) {
  mapState.hoveredHex = { hex_q: q, hex_r: r }
}

export function clearHoveredHex() {
  mapState.hoveredHex = null
}

export function setSelectedHex(q, r) {
  mapState.selectedHex = { hex_q: q, hex_r: r }
}

export function clearSelectedHex() {
  mapState.selectedHex = null
}

export function startDragDraw() {
  mapState.dragDrawing = true
  mapState.lastDragHex = null
}

export function endDragDraw() {
  mapState.dragDrawing = false
  mapState.lastDragHex = null
}

export function recordDragHex(q, r) {
  const key = `${q},${r}`
  if (mapState.lastDragHex === key) return false
  mapState.lastDragHex = key
  return true
}
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapState 状态机"
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapState.js frontend-console/tests/mapView.test.js && git commit -m "feat(map): extend mapState for pending bindings, drag, hover, selection"
```

---

## Task 2: 扩展 mapHexRenderer.js 绘制 pending 与悬停

**Files:**
- Modify: `frontend-console/views/mapHexRenderer.js`
- Test: `frontend-console/tests/mapView.test.js`

- [ ] **Step 1: 写 failing test**

在 `frontend-console/tests/mapView.test.js` 新增 describe：

```javascript
import {
  // ... 已有 import ...
  drawPendingTerrain,
  drawPendingBindings,
  drawHoverHighlight,
} from "../views/mapHexRenderer.js"

// ...

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
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapHexRenderer 绘制辅助"
```

Expected: FAIL，imports not found。

- [ ] **Step 3: 实现绘制函数**

在 `frontend-console/views/mapHexRenderer.js` 末尾追加：

```javascript
/**
 * 在已有地形上叠加半透明 pending 地形提示。
 */
export function drawPendingTerrain(ctx, pendingChanges, size, offsetX, offsetY) {
  const corners = hexCorners(size)
  ctx.save()
  ctx.globalAlpha = 0.4
  for (const change of Object.values(pendingChanges)) {
    const [cx, cy] = hexToPixel(change.hex_q, change.hex_r, size)
    const x = cx + offsetX
    const y = cy + offsetY
    const color = TERRAIN_COLORS[change.terrain_type] || TERRAIN_COLORS.grassland
    ctx.beginPath()
    for (let i = 0; i < 6; i++) {
      const [vx, vy] = corners[i]
      if (i === 0) ctx.moveTo(x + vx, y + vy)
      else ctx.lineTo(x + vx, y + vy)
    }
    ctx.closePath()
    ctx.fillStyle = color.fill
    ctx.fill()
  }
  ctx.restore()
}

/**
 * 绘制 pending 地点绑定（虚线框 + 中心星标）。
 */
export function drawPendingBindings(ctx, pendingBindings, size, offsetX, offsetY) {
  const corners = hexCorners(size)
  ctx.save()
  ctx.setLineDash([4, 3])
  for (const binding of Object.values(pendingBindings)) {
    const [cx, cy] = hexToPixel(binding.hex_q, binding.hex_r, size)
    const x = cx + offsetX
    const y = cy + offsetY
    ctx.beginPath()
    for (let i = 0; i < 6; i++) {
      const [vx, vy] = corners[i]
      if (i === 0) ctx.moveTo(x + vx, y + vy)
      else ctx.lineTo(x + vx, y + vy)
    }
    ctx.closePath()
    ctx.strokeStyle = binding.is_center ? "#FFD600" : "rgba(255, 214, 0, 0.7)"
    ctx.lineWidth = binding.is_center ? 3 : 1.5
    ctx.stroke()
    if (binding.is_center) {
      ctx.fillStyle = "#FFD600"
      ctx.font = "14px sans-serif"
      ctx.textAlign = "center"
      ctx.textBaseline = "middle"
      ctx.fillText("★", x, y)
    }
  }
  ctx.restore()
}

/**
 * 悬停 hex 白色描边高亮。
 */
export function drawHoverHighlight(ctx, q, r, size, offsetX, offsetY) {
  const corners = hexCorners(size)
  const [cx, cy] = hexToPixel(q, r, size)
  const x = cx + offsetX
  const y = cy + offsetY
  ctx.beginPath()
  for (let i = 0; i < 6; i++) {
    const [vx, vy] = corners[i]
    if (i === 0) ctx.moveTo(x + vx, y + vy)
    else ctx.lineTo(x + vx, y + vy)
  }
  ctx.closePath()
  ctx.strokeStyle = "rgba(255, 255, 255, 0.9)"
  ctx.lineWidth = 3
  ctx.stroke()
}
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapHexRenderer 绘制辅助"
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapHexRenderer.js frontend-console/tests/mapView.test.js && git commit -m "feat(map): add pending and hover highlight renderers"
```

---

## Task 3: 编辑面板显示 pending 绑定计数

**Files:**
- Modify: `frontend-console/views/mapEditPanel.js`
- Modify: `frontend-console/views/mapView.js`（调用 updateBindingPendingCount）
- Test: `frontend-console/tests/mapView.test.js`

- [ ] **Step 1: 写 failing test**

在 `frontend-console/tests/mapView.test.js` 新增：

```javascript
import renderEditPanel, { updatePendingCount, updateBindingPendingCount, toggleToolSections } from "../views/mapEditPanel.js"

// ...

describe("mapEditPanel 绑定计数", () => {
  it("updateBindingPendingCount 更新 DOM", () => {
    document.body.innerHTML = `<span id="map-binding-pending-count">0 个待绑定</span>`
    updateBindingPendingCount(3)
    expect(document.getElementById("map-binding-pending-count").textContent).toBe("3 个待绑定")
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapEditPanel 绑定计数"
```

Expected: FAIL，updateBindingPendingCount not found。

- [ ] **Step 3: 实现编辑面板扩展**

修改 `frontend-console/views/mapEditPanel.js`：

```javascript
// 在 bind section 内增加计数显示
<div class="map-edit-section" id="map-bind-section" style="display:none;">
  <h4>绑定地点</h4>
  <select class="form-select" id="map-bind-select">
    ${locOptions}
  </select>
  <p class="map-hint">选择地点后，点击或拖拽六边形绑定。点击中心格切换中心点。</p>
  <span class="map-pending-count" id="map-binding-pending-count">0 个待绑定</span>
</div>

// 新增导出函数
export function updateBindingPendingCount(count) {
  const el = document.getElementById("map-binding-pending-count")
  if (el) el.textContent = `${count} 个待绑定`
}
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapEditPanel 绑定计数"
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapEditPanel.js frontend-console/tests/mapView.test.js && git commit -m "feat(map): show pending binding count in edit panel"
```

---

## Task 4: 实现 Leaflet popup tooltip

**Files:**
- Modify: `frontend-console/views/mapView.js`
- Test: `frontend-console/tests/mapView.test.js`

- [ ] **Step 1: 写 failing test**

新增测试：

```javascript
describe("mapView tooltip", () => {
  it("_buildTooltipContent 对中心绑定返回地点名", () => {
    mapView._state = {
      map: { hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [{ hex_q: 1, hex_r: 1, terrain_type: "grassland" }],
      location_bindings: [{ hex_q: 1, hex_r: 1, location_entity_id: "loc1", is_center: true }],
    }
    mapView._locations = [{ id: "loc1", name: "洛阳" }]
    const html = mapView._buildTooltipContent(1, 1)
    expect(html).toContain("洛阳")
    expect(html).toContain("中心")
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapView tooltip"
```

Expected: FAIL，_buildTooltipContent not defined。

- [ ] **Step 3: 实现 tooltip**

在 `mapView.js` 中：

1. import 新增函数：

```javascript
import {
  mapState,
  resetMapState,
  stageTerrainChange,
  consumePendingChanges,
  popUndo,
  setHoveredHex,
  clearHoveredHex,
  startDragDraw,
  endDragDraw,
  recordDragHex,
} from "./mapState.js"
import {
  drawTerrain,
  drawBindings,
  drawPendingTerrain,
  drawPendingBindings,
  drawHoverHighlight,
  hexToPixel,
  pixelToHex,
  floodFillTerrain,
  TERRAIN_COLORS,
} from "./mapHexRenderer.js"
import renderEditPanel, { updatePendingCount, updateBindingPendingCount, toggleToolSections } from "./mapEditPanel.js"
```

2. 在 `_initLeaflet` 中绑定 canvas 鼠标事件：

```javascript
this._canvas.addEventListener("mousemove", (e) => this._handleCanvasMouseMove(e))
this._canvas.addEventListener("mouseout", () => this._handleCanvasMouseOut())
```

3. 新增方法：

```javascript
_handleCanvasMouseMove(e) {
  if (!this._canvas || !this._state) return
  const [q, r] = this._eventToHex(e)
  if (q == null) return
  setHoveredHex(q, r)
  if (mapState.mode === "edit") {
    if (mapState.dragDrawing) this._handleDragDraw(q, r)
    this._redraw()
    return
  }
  // 浏览模式：debounce 300ms 后显示 tooltip，避免频繁创建 popup
  if (this._tooltipDebounceTimer) clearTimeout(this._tooltipDebounceTimer)
  this._tooltipDebounceTimer = setTimeout(() => {
    this._showTooltip(q, r)
  }, 300)
  this._redraw()
},

_handleCanvasMouseOut() {
  clearHoveredHex()
  if (this._tooltipDebounceTimer) {
    clearTimeout(this._tooltipDebounceTimer)
    this._tooltipDebounceTimer = null
  }
  if (this._tooltipPopup) {
    this._leaflet.closePopup(this._tooltipPopup)
    this._tooltipPopup = null
  }
  this._redraw()
},

_showTooltip(q, r) {
  if (!this._leaflet) return
  const content = this._buildTooltipContent(q, r)
  if (!content) {
    if (this._tooltipPopup) {
      this._leaflet.closePopup(this._tooltipPopup)
      this._tooltipPopup = null
    }
    return
  }
  const cfg = this._state.map
  const [x, y] = hexToPixel(q, r, cfg.hex_size || 30)
  const latlng = window.L.latLng(y, x)
  if (this._tooltipPopup) {
    this._tooltipPopup.setLatLng(latlng).setContent(content)
  } else {
    this._tooltipPopup = window.L.popup({ closeButton: false, autoClose: false, className: "map-hex-tooltip" })
      .setLatLng(latlng)
      .setContent(content)
      .openOn(this._leaflet)
  }
},

_buildTooltipContent(q, r) {
  const binding = (this._state.location_bindings || []).find((b) => b.hex_q === q && b.hex_r === r)
  const tile = (this._state.tiles || []).find((t) => t.hex_q === q && t.hex_r === r)
  if (binding) {
    const name = this._locationName(binding.location_entity_id)
    const centerTag = binding.is_center ? "（中心）" : ""
    return `<div class="map-tooltip-title">${esc(name)}${centerTag}</div><div class="map-tooltip-sub">${esc(tile ? tile.terrain_type : "")}</div>`
  }
  if (tile) {
    return `<div class="map-tooltip-title">${esc(tile.terrain_type)}</div><div class="map-tooltip-sub">q:${q}, r:${r}</div>`
  }
  return ""
},
```

4. 在 `_redraw` 末尾添加悬停高亮：

```javascript
if (mapState.hoveredHex) {
  drawHoverHighlight(this._ctx, mapState.hoveredHex.hex_q, mapState.hoveredHex.hex_r, size, 0, 0)
}
```

5. 在 `_redraw` 中绘制 pending：

```javascript
drawPendingTerrain(this._ctx, mapState.pendingTerrainChanges, size, 0, 0)
drawPendingBindings(this._ctx, mapState.pendingBindings, size, 0, 0)
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapView tooltip"
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapView.js frontend-console/tests/mapView.test.js && git commit -m "feat(map): Leaflet popup tooltip and hover highlight"
```

---

## Task 5: 实现右侧详情面板

**Files:**
- Modify: `frontend-console/views/mapView.js`
- Modify: `frontend-console/styles.css`
- Test: `frontend-console/tests/mapView.test.js`

- [ ] **Step 1: 写 failing test**

```javascript
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
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapView 详情面板"
```

Expected: FAIL，_renderDetailPanel not defined。

- [ ] **Step 3: 实现详情面板**

1. 在 `_renderMapShell` 的 `.map-container` 中追加右侧面板：

```javascript
return `
  <div class="map-toolbar">...</div>
  <div class="map-container">
    <div id="map-leaflet" class="map-leaflet"></div>
    ${editPanelHtml ? `<div class="map-edit-panel">${editPanelHtml}</div>` : ""}
    <div id="map-detail-panel" class="map-detail-panel"></div>
  </div>
  <div class="map-filter-bar">...</div>
`
```

2. 新增 `_renderDetailPanel(q, r)` 和 `_updateDetailPanel(q, r)`：

```javascript
_renderDetailPanel(q, r) {
  const binding = (this._state.location_bindings || []).find((b) => b.hex_q === q && b.hex_r === r && b.is_center)
  if (binding) {
    const loc = this._locations.find((l) => l.id === binding.location_entity_id)
    const name = loc ? loc.name : "未命名地点"
    const summary = loc && loc.summary ? loc.summary : "暂无摘要"
    const bindingCount = (this._state.location_bindings || []).filter(
      (b) => b.location_entity_id === binding.location_entity_id
    ).length
    const hasDetail = this._hasDetailMap(binding.location_entity_id)
    const actionText = hasDetail ? "进入详图" : "创建详图"
    return `
      <div class="map-detail-header">${esc(name)}</div>
      <div class="map-detail-section">
        <div class="map-detail-label">摘要</div>
        <div class="map-detail-value">${esc(summary)}</div>
      </div>
      <div class="map-detail-section">
        <div class="map-detail-label">绑定格数</div>
        <div class="map-detail-value">${bindingCount}</div>
      </div>
      <div class="map-detail-actions">
        <button class="btn btn-sm btn-primary" data-action="map-detail-drill" data-id="${esc(binding.location_entity_id)}">${esc(actionText)}</button>
      </div>
    `
  }
  const tile = (this._state.tiles || []).find((t) => t.hex_q === q && t.hex_r === r)
  if (tile) {
    return `
      <div class="map-detail-header">地形：${esc(tile.terrain_type)}</div>
      <div class="map-detail-section">
        <div class="map-detail-label">坐标</div>
        <div class="map-detail-value">q:${q}, r:${r}</div>
      </div>
    `
  }
  return `<div class="map-detail-empty">点击地图查看详情</div>`
},

_updateDetailPanel(q, r) {
  const panel = document.getElementById("map-detail-panel")
  if (!panel) return
  panel.innerHTML = this._renderDetailPanel(q, r)
},
```

3. 在 `_handleBrowseClick` 中调用：

```javascript
_handleBrowseClick(q, r) {
  setSelectedHex(q, r)
  this._updateDetailPanel(q, r)
  // ... 保留原有 toast ...
}
```

4. 在 `_bindMapEvents` 中新增事件委托：

```javascript
"map-detail-drill": (_e, t) => {
  const id = t.getAttribute("data-id")
  if (id) this._onCenterClick(id)
},
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapView 详情面板"
```

Expected: PASS。

- [ ] **Step 5: 添加 CSS**

在 `frontend-console/styles.css` 追加：

```css
.map-detail-panel {
  width: 240px;
  flex-shrink: 0;
  border-left: 1px solid var(--border);
  background: var(--bg-elevated);
  padding: 12px;
  overflow-y: auto;
}

.map-detail-header {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 12px;
  word-break: break-word;
}

.map-detail-section {
  margin-bottom: 12px;
}

.map-detail-label {
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 4px;
}

.map-detail-value {
  font-size: 13px;
  word-break: break-word;
}

.map-detail-actions {
  margin-top: 16px;
}

.map-detail-empty {
  color: var(--text-dim);
  font-size: 13px;
}
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapView.js frontend-console/styles.css frontend-console/tests/mapView.test.js && git commit -m "feat(map): right-side detail panel for location center and terrain"
```

---

## Task 6: 实现拖拽绘制

**Files:**
- Modify: `frontend-console/views/mapView.js`
- Test: `frontend-console/tests/mapView.test.js`

- [ ] **Step 1: 写 failing test**

```javascript
describe("mapView 拖拽绘制", () => {
  it("_handleDragDraw brush 把新格加入 pending", () => {
    resetMapState()
    mapState.mode = "edit"
    mapState.activeTool = "brush"
    mapState.selectedTerrain = "water"
    startDragDraw()
    mapView._handleDragDraw(1, 1)
    mapView._handleDragDraw(1, 2)
    expect(Object.keys(mapState.pendingTerrainChanges)).toHaveLength(2)
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapView 拖拽绘制"
```

Expected: FAIL，_handleDragDraw not defined。

- [ ] **Step 3: 实现拖拽绘制**

1. 在 `_initLeaflet` 的 canvas 事件监听中增加：

```javascript
this._canvas.addEventListener("mousedown", (e) => this._handleCanvasMouseDown(e))
this._canvas.addEventListener("mouseup", () => this._handleCanvasMouseUp())
this._canvas.addEventListener("mouseleave", () => this._handleCanvasMouseUp())
```

2. 新增方法：

```javascript
_handleCanvasMouseDown(e) {
  if (!this._canvas || !this._state || mapState.mode !== "edit") return
  const [q, r] = this._eventToHex(e)
  if (q == null) return
  this._dragMoved = false
  startDragDraw()
  this._handleDragDraw(q, r)
  this._redraw()
},

_handleCanvasMouseUp() {
  if (!mapState.dragDrawing) return
  endDragDraw()
  // click 事件会在 mouseup 后触发，保留 _dragMoved 到 click 判断完成
  setTimeout(() => { this._dragMoved = false }, 0)
},

_handleDragDraw(q, r) {
  if (!recordDragHex(q, r)) return
  this._dragMoved = true
  const cfg = this._state.map
  if (q < 0 || q >= cfg.grid_width || r < 0 || r >= cfg.grid_height) return
  if (mapState.activeTool === "brush") {
    stageTerrainChange(q, r, mapState.selectedTerrain)
    updatePendingCount(Object.keys(mapState.pendingTerrainChanges).length)
  } else if (mapState.activeTool === "bind") {
    const entityId = mapState.selectedLocationEntityId
    if (!entityId) return
    // 默认非中心；中心点通过 bind section 的“设为中心”复选框控制
    stageBindingChange(entityId, q, r, !!mapState.bindCenterMode)
    updateBindingPendingCount(Object.keys(mapState.pendingBindings).length)
  }
},

_eventToHex(e) {
  if (!this._canvas || !this._leaflet) return [null, null]
  const rect = this._canvas.getBoundingClientRect()
  const px = e.clientX - rect.left
  const py = e.clientY - rect.top
  const origin = this._leaflet.latLngToContainerPoint([0, 0])
  const zoom = this._leaflet.getZoom()
  const scale = Math.pow(2, zoom)
  const worldX = (px - origin.x) / scale
  const worldY = (py - origin.y) / scale
  const cfg = this._state.map
  const size = cfg.hex_size || 30
  return pixelToHex(worldX, worldY, size)
},
```

3. 修改 `_handleEditClick` 以复用 `_eventToHex` 并触发拖拽去重：

```javascript
_handleCanvasClick(e) {
  if (!this._canvas || !this._state) return
  const [q, r] = this._eventToHex(e)
  if (q == null) return
  // 范围校验
  const cfg = this._state.map
  if (q < 0 || q >= cfg.grid_width || r < 0 || r >= cfg.grid_height) return
  if (mapState.mode === "edit") {
    // 拖拽过程中已经 stage 过，click 不再重复处理；纯单击则走 stage
    if (!this._dragMoved) {
      this._handleDragDraw(q, r)
    }
    this._redraw()
  } else {
    this._handleBrowseClick(q, r)
  }
},
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapView 拖拽绘制"
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapView.js frontend-console/tests/mapView.test.js && git commit -m "feat(map): drag-to-draw terrain and bindings"
```

---

## Task 7: 实现地点绑定批量保存

**Files:**
- Modify: `frontend-console/views/mapView.js`
- Modify: `frontend-console/views/mapEditPanel.js`（增加“设为中心”复选框）
- Test: `frontend-console/tests/mapView.test.js`

- [ ] **Step 1: 写 failing test**

```javascript
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
})
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapView 批量绑定保存"
```

Expected: FAIL，_applyBindings not defined。

- [ ] **Step 3: 实现批量绑定保存**

1. 在 `mapEditPanel.js` 的 bind section 增加“设为中心”复选框：

```html
<div class="map-edit-section" id="map-bind-section" style="display:none;">
  <h4>绑定地点</h4>
  <select class="form-select" id="map-bind-select">${locOptions}</select>
  <label class="map-checkbox">
    <input type="checkbox" id="map-bind-center" /> 设为中心点
  </label>
  <p class="map-hint">选择地点后，点击或拖拽六边形绑定。</p>
  <span class="map-pending-count" id="map-binding-pending-count">0 个待绑定</span>
</div>
```

2. 在 `mapView.js` 中读取复选框：

```javascript
// 在 _bindMapEvents 的 bindSelect change 监听后增加
const bindCenterCheck = document.getElementById("map-bind-center")
bindCenterCheck?.addEventListener("change", () => {
  mapState.bindCenterMode = bindCenterCheck.checked
})
```

3. 在 `_handleDragDraw` 的 bind 分支中使用：

```javascript
} else if (mapState.activeTool === "bind") {
  const entityId = mapState.selectedLocationEntityId
  if (!entityId) return
  const isCenter = !!mapState.bindCenterMode
  stageBindingChange(entityId, q, r, isCenter)
  updateBindingPendingCount(Object.keys(mapState.pendingBindings).length)
}
```

4. 新增 `_applyBindings`：

```javascript
async _applyBindings() {
  const bindings = Object.values(mapState.pendingBindings)
  if (bindings.length === 0) return
  const byEntity = {}
  for (const b of bindings) {
    if (!byEntity[b.location_entity_id]) byEntity[b.location_entity_id] = []
    byEntity[b.location_entity_id].push({ hex_q: b.hex_q, hex_r: b.hex_r, is_center: b.is_center })
  }
  try {
    for (const [entityId, hexes] of Object.entries(byEntity)) {
      await api.world.createLocationBindings(
        this._state.map.id,
        { location_entity_id: entityId, hexes },
        state.currentProjectId
      )
    }
    mapState.pendingBindings = {}
    updateBindingPendingCount(0)
  } catch (err) {
    toast(`绑定保存失败：${err.message}`, "error")
    throw err
  }
},
```

5. 修改 `_applyChanges` 为 `_applyAllChanges`：

```javascript
async _applyAllChanges() {
  const terrainChanges = Object.keys(mapState.pendingTerrainChanges).length
  const bindingChanges = Object.keys(mapState.pendingBindings).length
  if (terrainChanges === 0 && bindingChanges === 0) {
    toast("没有待应用的变更", "info")
    return
  }
  try {
    if (terrainChanges > 0) await this._applyTerrainChanges()
    if (bindingChanges > 0) await this._applyBindings()
    toast(`已应用 ${terrainChanges + bindingChanges} 个变更`, "success")
    await this._loadMapState(this._state.map.id)
    this._redraw()
  } catch (err) {
    // pending 保留，不重载
  }
},

async _applyTerrainChanges() {
  const changes = consumePendingChanges()
  if (changes.length === 0) return
  try {
    await api.world.batchUpdateTiles(this._state.map.id, { changes }, state.currentProjectId)
    updatePendingCount(0)
  } catch (err) {
    mapState.undoStack.pop()
    for (const c of changes) stageTerrainChange(c.hex_q, c.hex_r, c.terrain_type)
    updatePendingCount(Object.keys(mapState.pendingTerrainChanges).length)
    throw err
  }
},
```

6. 更新事件绑定：把 `map-apply` 改为 `_applyAllChanges`；`_saveAndExit` 也调用 `_applyAllChanges`。

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapView 批量绑定保存"
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapView.js frontend-console/views/mapEditPanel.js frontend-console/tests/mapView.test.js && git commit -m "feat(map): batch save location bindings"
```

---

## Task 8: 实现删除地图入口

**Files:**
- Modify: `frontend-console/views/mapView.js`
- Test: `frontend-console/tests/mapView.test.js`

- [ ] **Step 1: 写 failing test**

```javascript
describe("mapView 删除地图", () => {
  it("_renderList 显示删除按钮", () => {
    mapView._maps = [{ id: "m1", name: "九州", map_type: "world", grid_width: 30, grid_height: 20 }]
    const html = mapView._renderList()
    expect(html).toContain("data-action=\"map-delete\"")
    expect(html).toContain("删除")
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapView 删除地图"
```

Expected: FAIL，删除按钮不存在。

- [ ] **Step 3: 实现删除入口**

1. 修改 `_renderList`：

```javascript
const rows = this._maps.map((m) => `
  <tr class="clickable" data-action="map-open" data-id="${esc(m.id)}">
    <td>${esc(m.name)}</td>
    <td>${esc(m.map_type)}</td>
    <td>${m.grid_width}×${m.grid_height}</td>
    <td>
      <button class="btn btn-sm" data-action="map-open" data-id="${esc(m.id)}">打开</button>
      <button class="btn btn-sm btn-danger" data-action="map-delete" data-id="${esc(m.id)}">删除</button>
    </td>
  </tr>
`).join("")
```

2. 新增 `_deleteMap(mapId)`：

```javascript
_deleteMap(mapId) {
  const map = this._maps.find((m) => m.id === mapId)
  const name = map ? map.name : "该地图"
  confirmAction(
    `确定删除地图「${esc(name)}」？该操作不可恢复，子地图将变为顶层地图。`,
    async () => {
      try {
        await api.world.deleteMap(mapId, state.currentProjectId)
        toast("地图已删除", "success")
        await this._loadMaps()
        this._render("map-root")
      } catch (err) {
        toast(`删除失败：${err.message}`, "error")
      }
    },
    "删除"
  )
},
```

3. 在 `_bindListEvents` 中增加：

```javascript
"map-delete": (_e, t) => {
  const id = t.getAttribute("data-id")
  if (id) this._deleteMap(id)
},
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapView 删除地图"
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapView.js frontend-console/tests/mapView.test.js && git commit -m "feat(map): delete map entry with confirmation"
```

---

## Task 9: 实现地图元信息编辑 UI

**Files:**
- Modify: `frontend-console/views/mapView.js`
- Test: `frontend-console/tests/mapView.test.js`

- [ ] **Step 1: 写 failing test**

```javascript
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
})
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapView 地图设置"
```

Expected: FAIL，设置按钮不存在。

- [ ] **Step 3: 实现设置 UI**

1. 在 `_renderMapShell` 的工具栏增加按钮：

```javascript
const editBtn = mapState.mode === "edit"
  ? `<button class="btn btn-sm" data-action="map-exit-edit">退出编辑</button>`
  : `<button class="btn btn-sm" data-action="map-enter-edit">编辑</button>`

return `
  <div class="map-toolbar">
    <div class="map-breadcrumb">${breadcrumbs}</div>
    <div class="map-toolbar-right">
      <button class="btn btn-sm" data-action="map-back-list">地图列表</button>
      <button class="btn btn-sm" data-action="map-settings">地图设置</button>
      ${editBtn}
    </div>
  </div>
  ...
`
```

2. 新增 `_showSettingsModal()`：

```javascript
_showSettingsModal() {
  const cfg = this._state.map
  const formHtml = `
    <div class="form-group">
      <label>名称</label>
      <input class="form-input" id="map-settings-name" value="${esc(cfg.name)}" />
    </div>
    <div class="form-group">
      <label>描述</label>
      <textarea class="form-input" id="map-settings-desc" rows="3">${esc(cfg.description || "")}</textarea>
    </div>
  `
  showModal("地图设置", formHtml, [{
    text: "保存", class: "btn-primary", handler: async () => {
      const name = document.getElementById("map-settings-name")?.value.trim()
      if (!name) { toast("请输入地图名称", "warning"); return }
      const description = document.getElementById("map-settings-desc")?.value.trim()
      try {
        await api.world.updateMap(
          cfg.id,
          { name, description },
          state.currentProjectId
        )
        closeModal()
        toast("地图信息已更新", "success")
        await this._loadMapState(cfg.id)
        await this._loadMaps()
        this._render("map-root")
      } catch (err) {
        toast(`更新失败：${err.message}`, "error")
      }
    },
  }])
},
```

3. 在 `_bindMapEvents` 中增加：

```javascript
"map-settings": () => this._showSettingsModal(),
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js -t "mapView 地图设置"
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapView.js frontend-console/tests/mapView.test.js && git commit -m "feat(map): map settings modal for name and description"
```

---

## Task 10: 补充 CSS 样式

**Files:**
- Modify: `frontend-console/styles.css`

- [ ] **Step 1: 添加 pending、tooltip、设置相关样式**

在 `frontend-console/styles.css` 追加：

```css
/* pending 高亮已随 renderer 绘制，无需额外样式 */

.map-hex-tooltip .leaflet-popup-content-wrapper {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.map-hex-tooltip .leaflet-popup-tip {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
}

.map-tooltip-title {
  font-weight: 600;
  font-size: 13px;
}

.map-tooltip-sub {
  font-size: 11px;
  color: var(--text-dim);
}

.map-checkbox {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  margin-top: 8px;
}

.map-detail-panel .btn-danger {
  margin-left: 8px;
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/styles.css && git commit -m "style(map): tooltip and settings styles"
```

---

## Task 11: 运行完整前端测试套件

**Files:**
- Test: `frontend-console/tests/mapView.test.js` 及全部前端测试

- [ ] **Step 1: 运行完整测试**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run
```

Expected: 全部 PASS。如有失败，定位到具体测试并修复。

- [ ] **Step 2: Commit 修复（如有）**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add -A && git commit -m "test(map): fix tests after P0 frontend gap repairs"
```

---

## Task 12: 端到端手动验证

**Files:**
- 运行项目：根目录 `start.sh` 或 `docker-compose up`

- [ ] **Step 1: 启动项目**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && ./start.sh
```

或按 `development-guide.md` 启动后端和前端。

- [ ] **Step 2: 按验收清单手动验证**

1. 进入 world 视图 → map 子标签。
2. 创建世界地图 → 编辑模式 → 画笔 pending 显示半透明高亮。
3. 按住鼠标拖拽绘制多个格子 → 点击“应用”保存。
4. 切换到 bind 工具 → 选择地点 → 勾选“设为中心” → 点击/拖拽绑定多个格子 → 应用。
5. 退出编辑 → 悬停 hex 查看 Leaflet popup。
6. 点击地点中心 → 右侧详情面板显示名称/摘要/绑定格数/创建详图按钮。
7. 返回列表 → 点击某地图“删除” → 二次确认后删除。
8. 打开地图 → 点击“地图设置” → 改名/改描述 → 保存。

- [ ] **Step 3: 收尾 Commit（如验证后有微调）**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add -A && git commit -m "fix(map): manual e2e verification fixes"
```

---

## 自我审查

### Spec 覆盖检查

| Spec 要求 | 对应 Task |
|-----------|-----------|
| 状态层扩展（pendingBindings/drag/hover/selected） | Task 1 |
| pending 地形/绑定绘制 + 悬停高亮 | Task 2 |
| 编辑面板 pending 绑定计数 | Task 3 |
| Leaflet popup tooltip | Task 4 |
| 右侧详情面板 | Task 5 |
| 拖拽绘制 | Task 6 |
| 地点绑定批量保存 | Task 7 |
| 删除地图入口 | Task 8 |
| 地图元信息编辑 UI | Task 9 |
| 样式 | Task 10 |
| 测试 | Task 11 |
| 端到端验证 | Task 12 |

### Placeholder 检查

- 无 TBD/TODO。
- 每个 task 包含具体代码、命令、期望输出。
- 无模糊表述。

### 类型一致性检查

- `mapState.pendingBindings` 全程使用对象 key=`q,r`。
- `createLocationBindings` 请求体字段保持 `location_entity_id` / `hexes` / `hex_q` / `hex_r` / `is_center`。
- `api.world.updateMap` / `deleteMap` 签名与现有 `api.js` 一致。

---

## 执行方式选择

**Plan complete and saved to `docs/superpowers/plans/2026-06-15-map-p0-frontend-gaps.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
