/**
 * 地理关系布局核心。
 *
 * 只产出确定性位置、占用格和冲突；不渲染、不调用 API、不修改数据库。
 */

const DEFAULT_RADII = new Set([1, 2, 3, 5])

export function buildGeoLayout({
  nodes = [],
  relations = [],
  lockedLayouts = [],
  grid = {},
} = {}) {
  const width = Math.max(1, Number(grid.width) || 40)
  const height = Math.max(1, Number(grid.height) || 30)
  const lockedById = new Map(lockedLayouts.map((layout) => [layout.location_entity_id, layout]))
  const sorted = [...nodes].sort((a, b) => {
    const rank = relationRank(b.id, relations) - relationRank(a.id, relations)
    if (rank !== 0) return rank
    return String(a.name || a.id).localeCompare(String(b.name || b.id), "zh-Hans-CN")
  })
  const placed = []
  const occupied = new Map()
  const conflicts = []
  let expansionNeeded = false

  for (let index = 0; index < sorted.length; index++) {
    const node = sorted[index]
    const locked = lockedById.get(node.id)
    const radius = normalizeRadius(locked?.occupy_radius || node.occupy_radius || 1)
    const isLocked = locked?.locked === true
    const desired = locked
      ? { q: Number(locked.center_hex_q), r: Number(locked.center_hex_r) }
      : candidatePosition(index, sorted.length, width, height)
    const position = isLocked
      ? desired
      : findFreePosition(desired, radius, width, height, occupied)
    if (!position) {
      expansionNeeded = true
      conflicts.push({
        type: "layout_conflict",
        nodeId: node.id,
        reason: "insufficient_space",
      })
      continue
    }
    const cells = occupiedCells(position.q, position.r, radius)
    const overlap = cells.find((cell) => occupied.has(hexKey(cell.q, cell.r)))
    if (overlap && isLocked) {
      conflicts.push({
        type: "layout_conflict",
        nodeId: node.id,
        reason: "locked_overlap",
        withNodeId: occupied.get(hexKey(overlap.q, overlap.r)),
      })
    }
    for (const cell of cells) {
      occupied.set(hexKey(cell.q, cell.r), node.id)
    }
    placed.push({
      location_entity_id: node.id,
      center_hex_q: position.q,
      center_hex_r: position.r,
      occupy_radius: radius,
      locked: isLocked,
      layout_source: isLocked ? (locked.layout_source || "user_drag") : "auto_reflow",
      meta: {
        source_status: node.status || "canonical",
      },
    })
  }

  return {
    layouts: placed,
    occupied: [...occupied.entries()].map(([key, nodeId]) => {
      const [q, r] = key.split(",").map(Number)
      return { hex_q: q, hex_r: r, location_entity_id: nodeId }
    }),
    conflicts,
    expandedBounds: expansionNeeded
      ? { width: width + 8, height: height + 6 }
      : null,
  }
}

export function applyLayoutResize(layouts, locationEntityId, direction) {
  const delta = direction === "decrease" ? -1 : 1
  return layouts.map((layout) => {
    if (layout.location_entity_id !== locationEntityId) return layout
    const ordered = [1, 2, 3, 5]
    const currentIndex = Math.max(0, ordered.indexOf(normalizeRadius(layout.occupy_radius)))
    const nextIndex = Math.max(0, Math.min(ordered.length - 1, currentIndex + delta))
    return { ...layout, occupy_radius: ordered[nextIndex], layout_source: "user_resize" }
  })
}

export function occupiedCells(centerQ, centerR, radius = 1) {
  const cells = []
  const effective = Math.max(0, normalizeRadius(radius) - 1)
  for (let dq = -effective; dq <= effective; dq++) {
    for (let dr = -effective; dr <= effective; dr++) {
      const q = centerQ + dq
      const r = centerR + dr
      if (hexDistance(centerQ, centerR, q, r) <= effective) {
        cells.push({ q, r })
      }
    }
  }
  return cells
}

export function hexDistance(aq, ar, bq, br) {
  const as = -aq - ar
  const bs = -bq - br
  return Math.max(Math.abs(aq - bq), Math.abs(ar - br), Math.abs(as - bs))
}

function relationRank(id, relations) {
  return relations.filter((relation) => relation.source_id === id || relation.target_id === id).length
}

function candidatePosition(index, total, width, height) {
  const columns = Math.max(1, Math.min(6, Math.ceil(Math.sqrt(total))))
  const rows = Math.max(1, Math.ceil(total / columns))
  const col = index % columns
  const row = Math.floor(index / columns)
  return {
    q: clamp(Math.round(((col + 1) * width) / (columns + 1)), 0, width - 1),
    r: clamp(Math.round(((row + 1) * height) / (rows + 1)), 0, height - 1),
  }
}

function findFreePosition(desired, radius, width, height, occupied) {
  const maxRing = Math.max(width, height)
  for (let ring = 0; ring <= maxRing; ring++) {
    for (let dq = -ring; dq <= ring; dq++) {
      for (let dr = -ring; dr <= ring; dr++) {
        const q = clamp(desired.q + dq, 0, width - 1)
        const r = clamp(desired.r + dr, 0, height - 1)
        const cells = occupiedCells(q, r, radius)
        if (cells.every((cell) => inBounds(cell.q, cell.r, width, height) && !occupied.has(hexKey(cell.q, cell.r)))) {
          return { q, r }
        }
      }
    }
  }
  return null
}

function normalizeRadius(value) {
  const radius = Number(value) || 1
  if (DEFAULT_RADII.has(radius)) return radius
  return [1, 2, 3, 5].reduce((best, item) => (
    Math.abs(item - radius) < Math.abs(best - radius) ? item : best
  ), 1)
}

function inBounds(q, r, width, height) {
  return q >= 0 && r >= 0 && q < width && r < height
}

function hexKey(q, r) {
  return `${q},${r}`
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value))
}
