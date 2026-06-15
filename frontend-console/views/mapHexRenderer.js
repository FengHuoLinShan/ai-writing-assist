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

/**
 * 在 canvas 上绘制整个地形网格。
 * @param {CanvasRenderingContext2D} ctx
 * @param {Array<{hex_q:number,hex_r:number,terrain_type:string,elevation?:number}>} tiles
 * @param {number} size 六边形半径
 * @param {number} offsetX 画布偏移 x（地图坐标原点到画布原点）
 * @param {number} offsetY 画布偏移 y
 */
export function drawTerrain(ctx, tiles, size, offsetX, offsetY) {
  const corners = hexCorners(size)
  for (const tile of tiles) {
    const [cx, cy] = hexToPixel(tile.hex_q, tile.hex_r, size)
    const x = cx + offsetX
    const y = cy + offsetY
    const color = TERRAIN_COLORS[tile.terrain_type] || TERRAIN_COLORS.grassland
    ctx.beginPath()
    for (let i = 0; i < 6; i++) {
      const [vx, vy] = corners[i]
      if (i === 0) ctx.moveTo(x + vx, y + vy)
      else ctx.lineTo(x + vx, y + vy)
    }
    ctx.closePath()
    ctx.fillStyle = color.fill
    ctx.fill()
    ctx.strokeStyle = color.stroke
    ctx.lineWidth = 1
    ctx.stroke()
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
export function drawBindings(ctx, bindings, size, offsetX, offsetY, showBoundary) {
  const corners = hexCorners(size)
  for (const b of bindings) {
    const [cx, cy] = hexToPixel(b.hex_q, b.hex_r, size)
    const x = cx + offsetX
    const y = cy + offsetY
    if (b.is_center) {
      // 中心格：粗描边
      ctx.beginPath()
      for (let i = 0; i < 6; i++) {
        const [vx, vy] = corners[i]
        if (i === 0) ctx.moveTo(x + vx, y + vy)
        else ctx.lineTo(x + vx, y + vy)
      }
      ctx.closePath()
      ctx.strokeStyle = "#FFD600"
      ctx.lineWidth = 3
      ctx.stroke()
    } else if (showBoundary) {
      // 非中心格：虚线描边表示区域
      ctx.beginPath()
      for (let i = 0; i < 6; i++) {
        const [vx, vy] = corners[i]
        if (i === 0) ctx.moveTo(x + vx, y + vy)
        else ctx.lineTo(x + vx, y + vy)
      }
      ctx.closePath()
      ctx.strokeStyle = "rgba(255, 214, 0, 0.5)"
      ctx.lineWidth = 1.5
      ctx.setLineDash([4, 3])
      ctx.stroke()
      ctx.setLineDash([])
    }
  }
}

/**
 * 在已有地形上叠加半透明 pending 地形提示。
 */
export function drawPendingTerrain(ctx, pendingChanges, size, offsetX, offsetY) {
  const corners = hexCorners(size)
  ctx.save()
  ctx.globalAlpha = PENDING_TERRAIN_ALPHA
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
