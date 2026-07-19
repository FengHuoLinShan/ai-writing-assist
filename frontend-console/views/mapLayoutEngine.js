/**
 * 世界动态地图前端布局引擎。
 *
 * 输入 dashboard 队列和视图上下文，输出已避让的标签、聚合簇和上方语义气泡。
 * 这里不依赖 DOM 或 Leaflet，方便用单元测试约束高密度降级规则。
 */

const SEMANTIC_TYPES = new Set([
  "secret",
  "rule",
  "power_system",
  "knowledge",
  "legend",
  "semantic",
])

const VIEW_LABELS = {
  dashboard: "世界动态总控台",
  live: "活地图",
  lens: "叙事透镜",
}

const TYPE_LABELS = {
  character: "人物",
  location: "地点",
  faction: "势力",
  event: "事件",
  item: "物品",
  resource: "资源",
  crisis: "危机",
  route: "线路",
  organization: "组织",
  secret: "秘密",
  rule: "规则",
  power_system: "能力",
  knowledge: "知识",
}

export function boxesOverlap(a, b) {
  return a.x < b.x + b.width
    && a.x + a.width > b.x
    && a.y < b.y + b.height
    && a.y + a.height > b.y
}

export function buildMapLayout({
  dashboard = {},
  viewport = {},
  viewMode = "dashboard",
  focusEntityId = null,
  sceneId = null,
  lowMotion = false,
} = {}) {
  const width = Math.max(240, Number(viewport.width) || 640)
  const height = Math.max(180, Number(viewport.height) || 360)
  const mode = VIEW_LABELS[viewMode] ? viewMode : "dashboard"
  const queue = Array.isArray(dashboard.dynamic_queue) ? dashboard.dynamic_queue : []
  const scoredItems = queue
    .map((item, index) => ({
      item,
      index,
      score: scoreItem(item, { viewMode: mode, focusEntityId, sceneId }),
      anchor: getAnchor(item, index, width, height),
    }))
    .sort((a, b) => b.score - a.score || a.index - b.index)

  const semanticItems = scoredItems.filter(({ item }) => isSemanticItem(item))
  const semanticBubbles = placeSemanticBubbles(semanticItems, width, lowMotion)
  const reserved = semanticBubbles.map((bubble) => bubble.box)
  const spatialItems = scoredItems.filter(({ item }) => !isSemanticItem(item))
  const { labels, clusters, hiddenCount } = placeSpatialItems(spatialItems, {
    width,
    height,
    reserved,
    viewMode: mode,
  })

  return {
    viewMode: mode,
    motion: lowMotion ? "low" : "standard",
    density: densityFor(queue.length, width, height),
    labels,
    clusters,
    semanticBubbles,
    hiddenCount,
    layoutHint: `${VIEW_LABELS[mode]}：已自动避让、聚合并降级低优先级对象`,
  }
}

function scoreItem(item, context) {
  let score = Number(item.priority) || 0
  if (item.risk_level === "danger") score += 42
  if (item.risk_level === "warning") score += 22
  if (item.review_state === "candidate" || item.item_kind === "observation") score += 14
  if (item.fact_status === "confirmed" || item.item_kind === "fact") score += 8
  if (context.sceneId && (item.scene_id === context.sceneId || item.source_scene_id === context.sceneId)) {
    score += 32
  }
  if (context.focusEntityId && isFocusRelated(item, context.focusEntityId)) {
    score += context.viewMode === "lens" ? 90 : 36
  } else if (context.viewMode === "lens") {
    score -= 30
  }
  if (context.viewMode === "live" && item.item_kind === "fact") score += 12
  if (context.viewMode === "dashboard" && item.risk_level !== "info") score += 10
  return score
}

function isFocusRelated(item, focusEntityId) {
  const singularIds = [
    item.target_entity_id,
    item.entity_id,
    item.focus_entity_id,
    item.related_entity_id,
    item.location_entity_id,
    item.faction_entity_id,
  ]
  const relatedIds = [
    ...(Array.isArray(item.related_entity_ids) ? item.related_entity_ids : []),
    ...(Array.isArray(item.normalized_value?.related_entity_ids)
      ? item.normalized_value.related_entity_ids
      : []),
  ]
  return [...singularIds, ...relatedIds].filter(Boolean).includes(focusEntityId)
}

function isSemanticItem(item) {
  return SEMANTIC_TYPES.has(item.dynamic_type) || SEMANTIC_TYPES.has(item.object_type)
}

function placeSemanticBubbles(items, width, lowMotion) {
  const bubbles = []
  let x = 8
  let y = 8
  const rowHeight = 40
  for (const entry of items.slice(0, 8)) {
    const label = shortText(entry.item.title || entry.item.dynamic_type || "语义对象", 14)
    const bubbleWidth = clamp(label.length * 13 + 42, 92, Math.min(156, width - 16))
    if (x + bubbleWidth > width - 8) {
      x = 8
      y += rowHeight
    }
    const box = { x, y, width: bubbleWidth, height: 30 }
    bubbles.push({
      itemId: entry.item.item_id,
      title: entry.item.title || typeLabel(entry.item),
      label,
      dynamicType: entry.item.dynamic_type,
      box,
      anchored: Boolean(entry.item.anchor_to_location || entry.item.location_entity_id),
      motion: lowMotion ? "static" : "breathing",
    })
    x += bubbleWidth + 8
  }
  return bubbles
}

function placeSpatialItems(entries, { width, height, reserved, viewMode }) {
  const labels = []
  const clustersByKey = new Map()
  const occupied = [...reserved]
  const maxPlaced = viewMode === "lens"
    ? Math.max(4, Math.floor(width / 58))
    : Math.max(6, Math.floor((width * height) / 18000))
  let hiddenCount = 0

  for (const entry of entries) {
    if (labels.length >= maxPlaced && entry.score < 85) {
      addCluster(clustersByKey, entry)
      continue
    }
    const placed = placeLabel(entry, occupied, width, height)
    if (placed) {
      labels.push(placed)
      occupied.push(placed.box)
    } else {
      addCluster(clustersByKey, entry)
    }
  }

  const clusters = []
  for (const cluster of clustersByKey.values()) {
    const placed = placeCluster(cluster, occupied, width, height)
    if (placed) {
      clusters.push(placed)
      occupied.push(placed.box)
    } else {
      hiddenCount += cluster.items.length
    }
  }

  return { labels, clusters, hiddenCount }
}

function placeLabel(entry, occupied, width, height) {
  const levels = [
    { displayLevel: "full", width: 128, height: 28, label: shortText(entry.item.title || typeLabel(entry.item), 18) },
    { displayLevel: "short", width: 82, height: 24, label: shortText(entry.item.title || typeLabel(entry.item), 7) },
    { displayLevel: "icon", width: 30, height: 30, label: typeIcon(entry.item) },
  ]
  for (const level of levels) {
    const box = findBox(entry.anchor, level.width, level.height, width, height, occupied)
    if (!box) continue
    return {
      itemId: entry.item.item_id,
      title: entry.item.title || typeLabel(entry.item),
      label: level.label,
      objectType: entry.item.object_type,
      dynamicType: entry.item.dynamic_type,
      sourceKind: entry.item.source_kind || null,
      sourceId: entry.item.source_id || null,
      targetEntityId: entry.item.target_entity_id || entry.item.entity_id || null,
      q: entry.item.q ?? entry.item.hex_q ?? null,
      r: entry.item.r ?? entry.item.hex_r ?? null,
      opacity: Number(entry.item.opacity ?? 1),
      priority: entry.score,
      displayLevel: level.displayLevel,
      anchor: entry.anchor,
      box,
    }
  }
  return null
}

function placeCluster(cluster, occupied, width, height) {
  const box = findBox(cluster.anchor, 108, 28, width, height, occupied)
  if (!box) return null
  return {
    id: cluster.key,
    label: summarizeCluster(cluster.items),
    count: cluster.items.length,
    items: cluster.items.map(({ item }) => item),
    box,
  }
}

function findBox(anchor, boxWidth, boxHeight, width, height, occupied) {
  const attempts = [
    [8, -boxHeight - 8],
    [8, 8],
    [-boxWidth - 8, 8],
    [-boxWidth - 8, -boxHeight - 8],
    [-boxWidth / 2, -boxHeight - 16],
    [-boxWidth / 2, 16],
    [16, -boxHeight / 2],
    [-boxWidth - 16, -boxHeight / 2],
  ]
  for (const [dx, dy] of attempts) {
    const box = {
      x: clamp(anchor.x + dx, 4, width - boxWidth - 4),
      y: clamp(anchor.y + dy, 4, height - boxHeight - 4),
      width: boxWidth,
      height: boxHeight,
    }
    if (!occupied.some((other) => boxesOverlap(box, other))) {
      return box
    }
  }
  return null
}

function addCluster(clustersByKey, entry) {
  const key = `${Math.floor(entry.anchor.x / 72)}:${Math.floor(entry.anchor.y / 72)}:${entry.item.object_type || entry.item.dynamic_type || "object"}`
  if (!clustersByKey.has(key)) {
    clustersByKey.set(key, {
      key,
      anchor: { ...entry.anchor },
      items: [],
    })
  }
  clustersByKey.get(key).items.push(entry)
}

function summarizeCluster(entries) {
  const counts = new Map()
  for (const { item } of entries) {
    const label = typeLabel(item)
    counts.set(label, (counts.get(label) || 0) + 1)
  }
  return Array.from(counts.entries())
    .map(([label, count]) => `${label} ${count}`)
    .join(" / ")
}

function getAnchor(item, index, width, height) {
  if (item.anchor && Number.isFinite(item.anchor.x) && Number.isFinite(item.anchor.y)) {
    return {
      x: clamp(item.anchor.x, 0, width),
      y: clamp(item.anchor.y, 0, height),
    }
  }
  if (Number.isFinite(item.x) && Number.isFinite(item.y)) {
    return { x: clamp(item.x, 0, width), y: clamp(item.y, 0, height) }
  }
  if (Number.isFinite(item.hex_q) && Number.isFinite(item.hex_r)) {
    return {
      x: clamp(40 + item.hex_q * 28, 0, width),
      y: clamp(96 + item.hex_r * 24, 0, height),
    }
  }
  const hash = stableHash(`${item.item_id || item.title || "item"}:${index}`)
  const columns = Math.max(2, Math.floor(width / 120))
  const col = hash % columns
  const row = Math.floor(index / columns)
  return {
    x: clamp(60 + col * 116 + (hash % 17), 0, width),
    y: clamp(108 + row * 42 + (hash % 11), 0, height),
  }
}

function densityFor(count, width, height) {
  const density = count / Math.max(1, (width * height) / 10000)
  if (density > 2.2) return "compressed"
  if (density > 1.1) return "dense"
  return "normal"
}

function typeLabel(item) {
  return TYPE_LABELS[item.object_type] || TYPE_LABELS[item.dynamic_type] || "对象"
}

function typeIcon(item) {
  const label = typeLabel(item)
  return label.slice(0, 1)
}

function shortText(text, maxLength) {
  const value = String(text || "")
  if (value.length <= maxLength) return value
  return `${value.slice(0, Math.max(1, maxLength - 1))}…`
}

function clamp(value, min, max) {
  if (max < min) return min
  return Math.min(max, Math.max(min, value))
}

function stableHash(text) {
  let hash = 0
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) >>> 0
  }
  return hash
}
