/**
 * 六边形几何与渲染层 — PRD docs/PRD-动态地图功能.md §5.3 / §9.1 / §9.2 / §5.5
 *
 * 纯算法 + Canvas 2D，不依赖 Leaflet（由 mapView 在 Leaflet overlay canvas 上调用 draw）。
 * 轴向坐标 (q, r)，pointy-top 六边形。
 */

/** 地形配色（PRD §5.5），fill / stroke */
export const TERRAIN_COLORS = {
  grassland: { fill: "#7CB342", stroke: "#558B2F" },
  forest: { fill: "#2E7D32", stroke: "#1B5E20" },
  desert: { fill: "#F9A825", stroke: "#F57F17" },
  mountain: { fill: "#ECEFF1", stroke: "#CFD8DC" },
  water: { fill: "#1565C0", stroke: "#0D47A1" },
  city: { fill: "#D7CCC8", stroke: "#8D6E63" },
  road: { fill: "#BDBDBD", stroke: "#9E9E9E" },
  ruin: { fill: "#8D6E63", stroke: "#5D4037" },
  secret: { fill: "#7B1FA2", stroke: "#4A148C" },
  danger: { fill: "#C62828", stroke: "#B71C1C" },
}

/** 地形选项（侧边栏工具用） */
export const TERRAIN_OPTIONS = [
  { value: "grassland", label: "草原" },
  { value: "forest", label: "森林" },
  { value: "desert", label: "沙漠" },
  { value: "mountain", label: "山地" },
  { value: "water", label: "水域" },
  { value: "city", label: "城市" },
  { value: "road", label: "道路" },
  { value: "ruin", label: "遗迹" },
  { value: "secret", label: "秘密" },
  { value: "danger", label: "危险" },
]

/** pending 地形叠加透明度 */
const PENDING_TERRAIN_ALPHA = 0.4

/**
 * 轴向坐标 → 像素中心（pointy-top）
 * @param {number} q
 * @param {number} r
 * @param {number} size 六边形外接圆半径（像素）
 * @returns {[number, number]} [x, y]
 */
export function hexToPixel(q, r, size) {
  const x = size * (3 / 2) * q
  const y = size * Math.sqrt(3) * (r + q / 2)
  return [x, y]
}

/**
 * 像素 → 轴向坐标（含四舍五入）
 * @param {number} x
 * @param {number} y
 * @param {number} size
 * @returns {[number, number]} [q, r]
 */
export function pixelToHex(x, y, size) {
  const q = (2 / 3) * x / size
  const r = (-1 / 3 * x + Math.sqrt(3) / 3 * y) / size
  return hexRound(q, r)
}

/** 轴向坐标四舍五入到最近整数 hex */
export function hexRound(q, r) {
  const s = -q - r
  let rq = Math.round(q)
  let rr = Math.round(r)
  const rs = Math.round(s)
  const dq = Math.abs(rq - q)
  const dr = Math.abs(rr - r)
  const ds = Math.abs(rs - s)
  if (dq > dr && dq > ds) rq = -rr - rs
  else if (dr > ds) rr = -rq - rs
  return [rq, rr]
}

/** 六个邻居方向（pointy-top 轴向） */
const HEX_DIRECTIONS = [
  [1, 0], [1, -1], [0, -1],
  [-1, 0], [-1, 1], [0, 1],
]

/** 返回六边形 (q,r) 的六个邻居坐标 */
export function getNeighbors(q, r) {
  return HEX_DIRECTIONS.map(([dq, dr]) => [q + dq, r + dr])
}

/**
 * 油漆桶填充：从起始格 BFS 同地形连通区域，返回变更列表。
 * @param {number} startQ
 * @param {number} startR
 * @param {string} targetTerrain 当前要被替换的地形
 * @param {string} nextTerrain 新地形
 * @param {(q:number,r:number)=>string|null} getTileTerrain 查询某格当前地形
 * @returns {Array<{hex_q:number,hex_r:number,terrain_type:string}>}
 */
export function floodFillTerrain(startQ, startR, targetTerrain, nextTerrain, getTileTerrain) {
  const queue = [[startQ, startR]]
  const visited = new Set()
  const changes = []
  while (queue.length > 0) {
    const [q, r] = queue.shift()
    const key = `${q},${r}`
    if (visited.has(key)) continue
    visited.add(key)
    const terrain = getTileTerrain(q, r)
    if (terrain !== targetTerrain) continue
    changes.push({ hex_q: q, hex_r: r, terrain_type: nextTerrain })
    for (const [nq, nr] of getNeighbors(q, r)) {
      queue.push([nq, nr])
    }
  }
  return changes
}

/**
 * 计算单个六边形的 6 个顶点（相对中心）。
 * @param {number} size
 * @returns {Array<[number,number]>}
 */
export function hexCorners(size) {
  const corners = []
  for (let i = 0; i < 6; i++) {
    const angle = Math.PI / 180 * (60 * i - 30) // pointy-top: -30°起始
    corners.push([size * Math.cos(angle), size * Math.sin(angle)])
  }
  return corners
}

/** 按 size 缓存六边形顶点 */
const hexCornersCache = new Map()

function getHexCorners(size) {
  if (!hexCornersCache.has(size)) {
    hexCornersCache.set(size, hexCorners(size))
  }
  return hexCornersCache.get(size)
}

/**
 * 六边形绘制的深度原语。
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} q
 * @param {number} r
 * @param {number} size
 * @param {Object} style
 * @param {string} [style.fill]
 * @param {string} [style.stroke]
 * @param {number} [style.lineWidth]
 * @param {number[]} [style.lineDash]
 * @param {number} [offsetX]
 * @param {number} [offsetY]
 * @param {number} [opacity]
 */
export function drawHexCell(ctx, q, r, size, style, offsetX = 0, offsetY = 0, opacity = 1) {
  const corners = getHexCorners(size)
  const [cx, cy] = hexToPixel(q, r, size)
  const x = cx + offsetX
  const y = cy + offsetY

  ctx.save()
  ctx.globalAlpha = 1
  if (opacity !== 1) {
    ctx.globalAlpha = opacity
  }

  ctx.beginPath()
  for (let i = 0; i < 6; i++) {
    const [vx, vy] = corners[i]
    if (i === 0) ctx.moveTo(x + vx, y + vy)
    else ctx.lineTo(x + vx, y + vy)
  }
  ctx.closePath()

  if (style.fill) {
    ctx.fillStyle = style.fill
    ctx.fill()
  }
  if (style.stroke) {
    ctx.strokeStyle = style.stroke
    ctx.lineWidth = style.lineWidth ?? 1
    ctx.setLineDash(style.lineDash || [])
    ctx.stroke()
    ctx.setLineDash([])
  }

  ctx.restore()
}

/**
 * 在 canvas 上绘制整个地形网格。
 * @param {CanvasRenderingContext2D} ctx
 * @param {Array<{hex_q:number,hex_r:number,terrain_type:string,elevation?:number}>} tiles
 * @param {number} size 六边形半径
 * @param {number} offsetX 画布偏移 x（地图坐标原点到画布原点）
 * @param {number} offsetY 画布偏移 y
 */
export function drawTerrain(ctx, tiles, size, offsetX, offsetY, getOpacity = null) {
  for (const tile of tiles) {
    const opacity = getOpacity ? getOpacity(tile.hex_q, tile.hex_r) : 1
    const color = TERRAIN_COLORS[tile.terrain_type] || TERRAIN_COLORS.grassland
    drawHexCell(ctx, tile.hex_q, tile.hex_r, size, {
      fill: color.fill,
      stroke: color.stroke,
      lineWidth: 1,
    }, offsetX, offsetY, opacity)
  }
}

/**
 * 在 canvas 上绘制地点绑定区域边界与中心标记。
 * @param {CanvasRenderingContext2D} ctx
 * @param {Array} bindings MapLocationBinding[]
 * @param {number} size
 * @param {number} offsetX
 * @param {number} offsetY
 * @param {boolean} showBoundary 是否绘制非中心格的区域边界
 */
export function drawBindings(ctx, bindings, size, offsetX, offsetY, showBoundary, getOpacity = null) {
  for (const b of bindings) {
    const opacity = getOpacity ? getOpacity(b.hex_q, b.hex_r) : 1
    if (b.is_center) {
      drawHexCell(ctx, b.hex_q, b.hex_r, size, {
        stroke: "#FFD600",
        lineWidth: 3,
      }, offsetX, offsetY, opacity)
    } else if (showBoundary) {
      drawHexCell(ctx, b.hex_q, b.hex_r, size, {
        stroke: "rgba(255, 214, 0, 0.5)",
        lineWidth: 1.5,
        lineDash: [4, 3],
      }, offsetX, offsetY, opacity)
    }
  }
}

/**
 * 在已有地形上叠加半透明 pending 地形提示。
 */
export function drawPendingTerrain(ctx, pendingChanges, size, offsetX, offsetY, getOpacity = null) {
  for (const change of Object.values(pendingChanges)) {
    const opacity = getOpacity ? getOpacity(change.hex_q, change.hex_r) * PENDING_TERRAIN_ALPHA : PENDING_TERRAIN_ALPHA
    const color = TERRAIN_COLORS[change.terrain_type] || TERRAIN_COLORS.grassland
    drawHexCell(ctx, change.hex_q, change.hex_r, size, {
      fill: color.fill,
    }, offsetX, offsetY, opacity)
  }
}

/**
 * 绘制 pending 地点绑定（虚线框 + 中心星标）。
 */
export function drawPendingBindings(ctx, pendingBindings, size, offsetX, offsetY, getOpacity = null) {
  for (const binding of Object.values(pendingBindings)) {
    const opacity = getOpacity ? getOpacity(binding.hex_q, binding.hex_r) : 1
    drawHexCell(ctx, binding.hex_q, binding.hex_r, size, {
      stroke: binding.is_center ? "#FFD600" : "rgba(255, 214, 0, 0.7)",
      lineWidth: binding.is_center ? 3 : 1.5,
      lineDash: [4, 3],
    }, offsetX, offsetY, opacity)
    if (binding.is_center) {
      const [cx, cy] = hexToPixel(binding.hex_q, binding.hex_r, size)
      const x = cx + offsetX
      const y = cy + offsetY
      ctx.fillStyle = "#FFD600"
      ctx.font = "14px sans-serif"
      ctx.textAlign = "center"
      ctx.textBaseline = "middle"
      ctx.fillText("★", x, y)
    }
  }
}

/**
 * 悬停 hex 白色描边高亮。
 */
export function drawHoverHighlight(ctx, q, r, size, offsetX, offsetY, opacity = 1) {
  drawHexCell(ctx, q, r, size, {
    stroke: "rgba(255, 255, 255, 0.9)",
    lineWidth: 3,
  }, offsetX, offsetY, opacity)
}

const MARKER_STYLES = {
  character: { fill: "#FF9800", stroke: "#E65100", radius: 8 },
  event: { fill: "#2196F3", stroke: "#0D47A1", radius: 8 },
  item: { fill: "#9C27B0", stroke: "#4A148C", radius: 7 },
}

export function drawMarkers(ctx, markers, size, offsetX, offsetY) {
  if (!markers || markers.length === 0) return
  for (const marker of markers) {
    if (!marker.visible) continue
    const style = MARKER_STYLES[marker.marker_type] || MARKER_STYLES.character
    const [hx, hy] = hexToPixel(marker.hex_q, marker.hex_r, size)
    const x = hx + offsetX + (marker.offset_x || 0) * size
    const y = hy + offsetY + (marker.offset_y || 0) * size

    ctx.beginPath()
    ctx.arc(x, y, style.radius, 0, Math.PI * 2)
    ctx.fillStyle = style.fill
    ctx.fill()
    ctx.strokeStyle = style.stroke
    ctx.lineWidth = 1.5
    ctx.stroke()

    if (marker.label) {
      ctx.fillStyle = "#fff"
      ctx.font = "10px sans-serif"
      ctx.textAlign = "center"
      ctx.textBaseline = "bottom"
      const displayLabel = marker.label.length > 4 ? marker.label.slice(0, 4) : marker.label
      ctx.fillText(displayLabel, x, y - style.radius - 2)
    }
  }
}

// === P2: 势力范围渲染 ===

/**
 * 从 faction ID 生成确定性颜色（哈希算法）。
 * @param {string} factionId
 * @returns {string} 十六进制颜色字符串（如 "#7B1FA2"）
 */
export function hashColor(factionId) {
  let hash = 0
  for (let i = 0; i < factionId.length; i++) {
    hash = ((hash << 5) - hash) + factionId.charCodeAt(i)
    hash |= 0
  }
  const r = (Math.abs(hash) >> 16) & 0xFF
  const g = (Math.abs(hash) >> 8) & 0xFF
  const b = Math.abs(hash) & 0xFF
  return `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`
}

/**
 * 在 canvas 上绘制势力范围半透明叠加层。
 * @param {CanvasRenderingContext2D} ctx
 * @param {Array<{faction_id:string,hexes:Array<{hex_q:number,hex_r:number}>}>} territories
 * @param {number} size 六边形半径
 * @param {number} offsetX 画布偏移 x
 * @param {number} offsetY 画布偏移 y
 * @param {Object<string,string>} factionColors faction ID → 自定义颜色的映射（可选）
 */
export function drawTerritories(ctx, territories, size, offsetX, offsetY, factionColors, getOpacity = null) {
  if (!territories || territories.length === 0) return
  const colors = factionColors || {}
  for (const t of territories) {
    const color = colors[t.faction_id] || hashColor(t.faction_id)
    const fillColor = color + "66" // 40% alpha
    for (const h of t.hexes || []) {
      const opacity = getOpacity ? getOpacity(h.hex_q, h.hex_r) : 1
      drawHexCell(ctx, h.hex_q, h.hex_r, size, {
        fill: fillColor,
        stroke: color + "AA",
        lineWidth: 1,
      }, offsetX, offsetY, opacity)
    }
  }
}
