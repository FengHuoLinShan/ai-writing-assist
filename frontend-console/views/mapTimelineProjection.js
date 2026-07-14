import { hexToPixel } from "./mapHexRenderer.js"

export const MAP_TIMELINE_TRACKS = Object.freeze([
  { key: "journey", label: "人物旅程" },
  { key: "territory", label: "势力范围" },
  { key: "crisis", label: "危机扩散" },
  { key: "resource", label: "资源控制" },
  { key: "status", label: "状态变化" },
  { key: "world", label: "世界动态" },
])

const TRACK_KEYS = new Set(MAP_TIMELINE_TRACKS.map((track) => track.key))

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function sceneNumber(value) {
  if (value === null || value === undefined || value === "") return null
  const number = Number(value)
  return Number.isInteger(number) && number >= 0 ? number : null
}

function selectedTrackKeys(selectedTracks = {}) {
  return new Set(
    MAP_TIMELINE_TRACKS
      .filter((track) => selectedTracks[track.key] !== false)
      .map((track) => track.key),
  )
}

function itemTrack(item = {}) {
  if (TRACK_KEYS.has(item.track)) return item.track
  return {
    location: "journey",
    position_change: "journey",
    movement: "journey",
    boundary: "territory",
    territory: "territory",
    crisis: "crisis",
    resource: "resource",
    status: "status",
  }[item.dynamic_type || item.normalized_value?.type] || "world"
}

export function createMapTimelineState() {
  return {
    loading: false,
    loaded: false,
    error: null,
    data: null,
    stateAt: null,
    stateLoading: false,
    stateError: null,
    sceneIndex: null,
    activeIndex: 0,
    playing: false,
    includeCandidates: false,
    speedMs: 1600,
    selectedTracks: Object.fromEntries(MAP_TIMELINE_TRACKS.map(({ key }) => [key, true])),
  }
}

export function normalizeMapTimelineResponse(payload = {}) {
  const deltas = asArray(payload.deltas)
  const candidates = asArray(payload.candidates)
  const conflicts = asArray(payload.conflicts)
  const continuityIssues = asArray(payload.continuity_issues)
  const sceneByIndex = new Map()

  for (const scene of asArray(payload.scenes)) {
    const index = sceneNumber(scene?.scene_index)
    if (index === null) continue
    sceneByIndex.set(index, {
      ...scene,
      scene_index: index,
      delta_count: Number(scene.delta_count || 0),
      candidate_count: Number(scene.candidate_count || 0),
      conflict_count: Number(scene.conflict_count || 0),
      continuity_issue_count: Number(scene.continuity_issue_count || 0),
    })
  }

  const ensureScene = (rawIndex) => {
    const index = sceneNumber(rawIndex)
    if (index === null || sceneByIndex.has(index)) return
    sceneByIndex.set(index, {
      scene_index: index,
      delta_count: 0,
      candidate_count: 0,
      conflict_count: 0,
      continuity_issue_count: 0,
    })
  }
  deltas.forEach((item) => ensureScene(item?.scene_index))
  candidates.forEach((item) => ensureScene(item?.scene_index ?? item?.time_anchor?.scene_index))
  conflicts.forEach((item) => ensureScene(item?.scene_index))
  continuityIssues.forEach((item) => ensureScene(item?.to_scene_index))

  return {
    ...payload,
    scenes: [...sceneByIndex.values()].sort((a, b) => a.scene_index - b.scene_index),
    deltas,
    candidates,
    conflicts,
    continuity_issues: continuityIssues,
    undated_facts: asArray(payload.undated_facts),
    untyped_facts: asArray(payload.untyped_facts),
    total: Number(payload.total ?? deltas.length),
    skip: Number(payload.skip || 0),
    limit: Number(payload.limit || 500),
    has_more: Boolean(payload.has_more),
  }
}

export function normalizeMapStateAtResponse(payload = {}) {
  return {
    ...payload,
    scene_index: sceneNumber(payload.scene_index),
    items: asArray(payload.items),
    conflicts: asArray(payload.conflicts),
    total: Number(payload.total ?? asArray(payload.items).length),
    skip: Number(payload.skip || 0),
    limit: Number(payload.limit || 500),
    has_more: Boolean(payload.has_more),
  }
}

export function filterTimelineItems(items, selectedTracks = {}) {
  const selected = selectedTrackKeys(selectedTracks)
  return asArray(items).filter((item) => selected.has(itemTrack(item)))
}

export function timelineItemsAtScene(items, sceneIndex, selectedTracks = {}) {
  const target = sceneNumber(sceneIndex)
  return filterTimelineItems(items, selectedTracks).filter((item) => (
    sceneNumber(item?.scene_index ?? item?.time_anchor?.scene_index) === target
  ))
}

export function mapDynamicNormalizationLabel(state) {
  return {
    typed: "已结构化",
    legacy_normalized: "旧记录已兼容",
    untyped: "尚未结构化",
    invalid: "结构化异常",
  }[state] || "已结构化"
}

export function mapDynamicTrackLabel(trackOrItem) {
  const target = trackOrItem && typeof trackOrItem === "object"
    ? trackOrItem
    : { track: trackOrItem }
  return MAP_TIMELINE_TRACKS.find((item) => item.key === itemTrack(target))?.label
    || "世界动态"
}

export function formatMapDynamicValue(value, fallback = "状态已记录") {
  if (!value || typeof value !== "object") return fallback
  const type = value.type || ""
  if (type === "location") {
    return value.location_name || value.label || value.place_name || "位置已更新"
  }
  if (type === "route_state") {
    return {
      open: "线路开放",
      restricted: "线路受限",
      blocked: "线路阻断",
    }[value.state] || "线路状态已更新"
  }
  if (type === "status") {
    const label = value.field_label || value.field_key || "状态"
    const current = value.value ?? value.current ?? value.after
    return current === undefined || current === null || current === ""
      ? `${label}已更新`
      : `${label}：${String(current)}`
  }
  if (type === "boundary") {
    return value.controller_name ? `${value.controller_name}的范围已更新` : "势力范围已更新"
  }
  if (type === "resource") {
    const resource = value.resource_name || value.resource_key || "资源"
    const controller = value.controller_name || value.controller || value.state
    return controller ? `${resource}：${controller}` : `${resource}状态已更新`
  }
  if (type === "terrain") return value.state ? `地形：${value.state}` : "地形状态已更新"
  if (type === "crisis") {
    const crisis = value.crisis_name || value.crisis_key || "危机"
    return value.severity === undefined ? `${crisis}已更新` : `${crisis} · 强度 ${value.severity}`
  }
  if (type === "semantic") return value.summary || "语义关联已记录"
  return fallback
}

export function timelineAnchorPoint(anchor = {}) {
  const source = anchor || {}
  const q = source.hex_q ?? source.representative_q ?? source.q
  const r = source.hex_r ?? source.representative_r ?? source.r
  const numericQ = Number(q)
  const numericR = Number(r)
  if (!Number.isFinite(numericQ) || !Number.isFinite(numericR)) return null
  return { q: numericQ, r: numericR }
}

function drawPoint(ctx, point, size, { color, candidate = false, radius = 5 } = {}) {
  const [x, y] = hexToPixel(point.q, point.r, size)
  ctx.save()
  ctx.beginPath()
  ctx.setLineDash(candidate ? [5, 4] : [])
  ctx.arc(x, y, radius, 0, Math.PI * 2)
  ctx.fillStyle = candidate ? "rgba(245, 158, 11, 0.22)" : "rgba(14, 165, 233, 0.25)"
  ctx.strokeStyle = color
  ctx.lineWidth = candidate ? 2 : 2.5
  ctx.fill()
  ctx.stroke()
  ctx.restore()
}

function drawArrow(ctx, from, to, size) {
  const [fromX, fromY] = hexToPixel(from.q, from.r, size)
  const [toX, toY] = hexToPixel(to.q, to.r, size)
  const angle = Math.atan2(toY - fromY, toX - fromX)
  const head = Math.max(5, size * 0.24)
  ctx.save()
  ctx.beginPath()
  ctx.moveTo(fromX, fromY)
  ctx.lineTo(toX, toY)
  ctx.lineTo(toX - head * Math.cos(angle - Math.PI / 6), toY - head * Math.sin(angle - Math.PI / 6))
  ctx.moveTo(toX, toY)
  ctx.lineTo(toX - head * Math.cos(angle + Math.PI / 6), toY - head * Math.sin(angle + Math.PI / 6))
  ctx.strokeStyle = "#0ea5e9"
  ctx.lineWidth = 2.5
  ctx.setLineDash([])
  ctx.stroke()
  ctx.restore()
}

function valueHexes(value = {}) {
  const source = value || {}
  const candidates = source.hexes || source.affected_hexes || source.boundary_hexes || []
  return asArray(candidates).map(timelineAnchorPoint).filter(Boolean)
}

function stableProjectionValue(value) {
  if (value === null || value === undefined) return String(value)
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableProjectionValue(item)).join(",")}]`
  }
  if (typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => (
      `${JSON.stringify(key)}:${stableProjectionValue(value[key])}`
    )).join(",")}}`
  }
  return JSON.stringify(value)
}

function candidateProjectionSignature(candidate = {}) {
  return stableProjectionValue({
    id: candidate.id ?? null,
    item_id: candidate.item_id ?? null,
    scene_index: candidate.scene_index ?? null,
    track: candidate.track ?? null,
    dynamic_type: candidate.dynamic_type ?? null,
    spatial_anchor: candidate.spatial_anchor ?? null,
    normalized_value: candidate.normalized_value ?? null,
  })
}

export function timelineProjectionSignature(projection = {}) {
  const stateIds = asArray(projection.stateItems)
    .flatMap((item) => item.source_fact_ids || [])
  const deltaIds = asArray(projection.deltas).map((item) => item.delta_id || "")
  const candidateSignatures = projection.includeCandidates
    ? asArray(projection.candidates).map(candidateProjectionSignature).sort()
    : []
  const tracks = Object.entries(projection.selectedTracks || {})
    .filter(([, enabled]) => enabled !== false)
    .map(([key]) => key)
    .sort()
  return [
    projection.projectionToken || "",
    projection.sceneIndex ?? "",
    tracks.join(","),
    stateIds.join(","),
    deltaIds.join(","),
    candidateSignatures.join(","),
  ].join(":")
}

export function drawTimelineProjection(
  ctx,
  projection = {},
  { hexSize = 30, isVisible = () => true } = {},
) {
  if (!ctx || projection.sceneIndex === null || projection.sceneIndex === undefined) return
  const sceneIndex = sceneNumber(projection.sceneIndex)
  const stateItems = filterTimelineItems(projection.stateItems, projection.selectedTracks)
  const deltas = timelineItemsAtScene(projection.deltas, sceneIndex, projection.selectedTracks)
  const candidates = projection.includeCandidates
    ? timelineItemsAtScene(projection.candidates, sceneIndex, projection.selectedTracks)
    : []

  for (const item of stateItems) {
    const anchor = timelineAnchorPoint(item.spatial_anchor)
    if (anchor && isVisible(anchor)) drawPoint(ctx, anchor, hexSize, { color: "#0284c7" })
    for (const hex of valueHexes(item.normalized_value)) {
      if (isVisible(hex)) drawPoint(ctx, hex, hexSize, { color: "#2563eb", radius: 3.5 })
    }
  }
  for (const delta of deltas) {
    const before = timelineAnchorPoint(delta.spatial_anchor_before)
    const after = timelineAnchorPoint(delta.spatial_anchor_after)
    if (before && after && (isVisible(before) || isVisible(after))) {
      drawArrow(ctx, before, after, hexSize)
    } else if (after && isVisible(after)) {
      drawPoint(ctx, after, hexSize, { color: "#0284c7" })
    }
  }
  for (const candidate of candidates) {
    const anchor = timelineAnchorPoint(candidate.spatial_anchor)
    if (anchor && isVisible(anchor)) {
      drawPoint(ctx, anchor, hexSize, { color: "#d97706", candidate: true })
    }
    for (const hex of valueHexes(candidate.normalized_value)) {
      if (isVisible(hex)) {
        drawPoint(ctx, hex, hexSize, {
          color: "#d97706",
          candidate: true,
          radius: 3.5,
        })
      }
    }
  }
}
