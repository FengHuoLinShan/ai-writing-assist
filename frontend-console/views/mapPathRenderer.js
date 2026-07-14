import { hexToPixel } from "./mapHexRenderer.js"

export const MAP_PATH_PROFILES = Object.freeze({
  major_road: { label: "主干道", category: "transport", color: "#D7B46A", casing: "#665035", width: 0.28, dash: [] },
  street: { label: "街道", category: "transport", color: "#C7B99A", casing: "#716B61", width: 0.18, dash: [] },
  dirt_trail: { label: "土路", category: "transport", color: "#9A744B", casing: "#60452E", width: 0.14, dash: [0.18, 0.12] },
  rail: { label: "铁路", category: "transport", color: "#E5E7EB", casing: "#31343A", width: 0.16, dash: [0.08, 0.08] },
  river: { label: "河流", category: "water", color: "#3B82F6", casing: "#1D4ED8", width: 0.34, dash: [] },
  stream: { label: "溪流", category: "water", color: "#67B7F7", casing: "#287DB5", width: 0.17, dash: [] },
  canal: { label: "运河", category: "water", color: "#4FA3D1", casing: "#236584", width: 0.24, dash: [] },
})

export function normalizePathState(payload = {}) {
  const paths = payload.paths || []
  return {
    editor_revision: Number(payload.editor_revision || 0),
    path_layers: payload.path_layers || payload.layers || [],
    paths,
    nodes: payload.nodes || payload.path_nodes || paths.flatMap((path) => path.nodes || []),
  }
}

function pointDistanceSq(point, start, end) {
  const dx = end.q - start.q
  const dy = end.r - start.r
  if (dx === 0 && dy === 0) return (point.q - start.q) ** 2 + (point.r - start.r) ** 2
  const t = Math.max(0, Math.min(1, ((point.q - start.q) * dx + (point.r - start.r) * dy) / (dx * dx + dy * dy)))
  const q = start.q + t * dx
  const r = start.r + t * dy
  return (point.q - q) ** 2 + (point.r - r) ** 2
}

/** Ramer–Douglas–Peucker，输入和输出都是连续轴向坐标。 */
export function simplifyPathNodes(nodes = [], tolerance = 0.08) {
  if (nodes.length <= 2) return nodes.map((node) => ({ ...node }))
  const sqTolerance = tolerance * tolerance
  const simplify = (startIndex, endIndex, output) => {
    let maxDistance = sqTolerance
    let splitIndex = null
    for (let index = startIndex + 1; index < endIndex; index += 1) {
      const distance = pointDistanceSq(nodes[index], nodes[startIndex], nodes[endIndex])
      if (distance > maxDistance) {
        maxDistance = distance
        splitIndex = index
      }
    }
    if (splitIndex != null) {
      if (splitIndex - startIndex > 1) simplify(startIndex, splitIndex, output)
      output.push({ ...nodes[splitIndex] })
      if (endIndex - splitIndex > 1) simplify(splitIndex, endIndex, output)
    }
  }
  const output = [{ ...nodes[0] }]
  simplify(0, nodes.length - 1, output)
  output.push({ ...nodes[nodes.length - 1] })
  return output
}

export function simplifyPathToLimit(nodes = [], limit = 500) {
  let tolerance = 0.08
  let simplified = simplifyPathNodes(nodes, tolerance)
  while (simplified.length > limit && tolerance < 2) {
    tolerance *= 1.5
    simplified = simplifyPathNodes(nodes, tolerance)
  }
  return { nodes: simplified, tolerance, overLimit: simplified.length > limit }
}

export function pathNodesFor(path, allNodes = []) {
  const embedded = path?.nodes
  const nodes = Array.isArray(embedded)
    ? embedded
    : (allNodes || []).filter((node) => node.path_id === path?.id)
  return nodes.map((node, index) => ({
    ...node,
    q: Number(node.q ?? node.hex_q),
    r: Number(node.r ?? node.hex_r),
    sort_order: Number(node.sort_order ?? index),
    width_scale: Number(node.width_scale ?? 1),
    tension: Number(node.tension ?? 0.5),
  })).filter((node) => Number.isFinite(node.q) && Number.isFinite(node.r))
    .sort((a, b) => a.sort_order - b.sort_order)
}

export function pathBounds(nodes = []) {
  if (!nodes.length) return null
  return nodes.reduce((bounds, node) => ({
    minQ: Math.min(bounds.minQ, node.q),
    maxQ: Math.max(bounds.maxQ, node.q),
    minR: Math.min(bounds.minR, node.r),
    maxR: Math.max(bounds.maxR, node.r),
  }), { minQ: Infinity, maxQ: -Infinity, minR: Infinity, maxR: -Infinity })
}

export function pathIntersectsViewport(nodes, viewport) {
  if (!viewport) return true
  const bounds = pathBounds(nodes)
  if (!bounds) return false
  return bounds.maxQ >= viewport.minQ && bounds.minQ <= viewport.maxQ
    && bounds.maxR >= viewport.minR && bounds.minR <= viewport.maxR
}

function catmullRomPoint(p0, p1, p2, p3, t, tension) {
  const scale = Math.max(0, Math.min(1, tension))
  const t2 = t * t
  const t3 = t2 * t
  const h00 = 2 * t3 - 3 * t2 + 1
  const h10 = t3 - 2 * t2 + t
  const h01 = -2 * t3 + 3 * t2
  const h11 = t3 - t2
  return {
    q: h00 * p1.q + h10 * (p2.q - p0.q) * scale
      + h01 * p2.q + h11 * (p3.q - p1.q) * scale,
    r: h00 * p1.r + h10 * (p2.r - p0.r) * scale
      + h01 * p2.r + h11 * (p3.r - p1.r) * scale,
  }
}

/** 生成渲染、命中测试共用的平滑样本。 */
export function samplePathGeometry(nodes = [], stepsPerSegment = 8) {
  if (nodes.length < 2) return nodes.map((node) => ({ ...node }))
  const samples = []
  for (let index = 0; index < nodes.length - 1; index += 1) {
    const p0 = nodes[Math.max(0, index - 1)]
    const p1 = nodes[index]
    const p2 = nodes[index + 1]
    const p3 = nodes[Math.min(nodes.length - 1, index + 2)]
    for (let step = 0; step < stepsPerSegment; step += 1) {
      const t = step / stepsPerSegment
      const point = catmullRomPoint(p0, p1, p2, p3, t, p1.tension ?? 0.5)
      samples.push({
        ...point,
        width_scale: Number(p1.width_scale ?? 1)
          + (Number(p2.width_scale ?? 1) - Number(p1.width_scale ?? 1)) * t,
        segment_type: p1.segment_type || null,
      })
    }
  }
  samples.push({ ...nodes.at(-1), width_scale: Number(nodes.at(-1).width_scale ?? 1) })
  return samples
}

function styleFor(path, segmentType = null, size = 30) {
  const profile = MAP_PATH_PROFILES[segmentType || path.path_type] || MAP_PATH_PROFILES.major_road
  const style = path.style || path.style_json || {}
  return {
    color: /^#[0-9a-f]{6}$/i.test(style.color || "") ? style.color : profile.color,
    casing: /^#[0-9a-f]{6}$/i.test(style.casing_color || "") ? style.casing_color : profile.casing,
    widthPixels: style.width == null
      ? size * profile.width
      : Math.max(0.25, Math.min(32, Number(style.width))),
    dash: Array.isArray(style.dash) ? style.dash.slice(0, 4).map(Number) : profile.dash,
  }
}

function strokeSamples(ctx, samples, path, size, casing = false) {
  if (samples.length < 2) return
  // 逐段绘制以支持变宽和节点 segment_type。
  for (let index = 0; index < samples.length - 1; index += 1) {
    const current = samples[index]
    const next = samples[index + 1]
    const style = styleFor(path, current.segment_type, size)
    const [x1, y1] = hexToPixel(current.q, current.r, size)
    const [x2, y2] = hexToPixel(next.q, next.r, size)
    ctx.beginPath()
    ctx.moveTo(x1, y1)
    ctx.lineTo(x2, y2)
    ctx.lineCap = "round"
    ctx.lineJoin = "round"
    ctx.strokeStyle = casing ? style.casing : style.color
    const scale = (Number(current.width_scale || 1) + Number(next.width_scale || 1)) / 2
    ctx.lineWidth = style.widthPixels * scale + (casing ? Math.max(2, size * 0.08) : 0)
    ctx.setLineDash((style.dash || []).map((value) => value * size))
    ctx.stroke()
  }
  ctx.setLineDash([])
}

export function drawMapPaths(ctx, paths = [], allNodes = [], {
  hexSize = 30,
  isVisible = () => true,
  opacityFor = () => 1,
  viewport = null,
  selectedPathId = null,
  selectedNodeIndex = null,
  focusedPathId = null,
  editMode = false,
  geometryCache = null,
} = {}) {
  const queued = []
  for (const path of paths) {
    if (path.status === "archived" && path.id !== focusedPathId) continue
    if (path.visible === false || !isVisible(path)) continue
    const nodes = pathNodesFor(path, allNodes)
    if (!pathIntersectsViewport(nodes, viewport)) continue
    const cacheKey = `${path.id || path.client_id}:${path.content_revision || 0}`
    let samples = geometryCache?.get(cacheKey)
    if (!samples) {
      samples = samplePathGeometry(nodes)
      geometryCache?.set(cacheKey, samples)
    }
    queued.push({ path, nodes, samples })
  }
  for (const { path, samples } of queued) {
    ctx.save()
    ctx.globalAlpha *= Math.max(0, Math.min(1, Number(path.opacity ?? 1) * opacityFor(path)))
    strokeSamples(ctx, samples, path, hexSize, true)
    strokeSamples(ctx, samples, path, hexSize, false)
    if (path.id === focusedPathId || path.id === selectedPathId) {
      ctx.globalAlpha = 1
      ctx.strokeStyle = path.id === focusedPathId ? "#F59E0B" : "#FFFFFF"
      ctx.lineWidth = Math.max(2, hexSize * 0.08)
      ctx.setLineDash([hexSize * 0.22, hexSize * 0.12])
      ctx.beginPath()
      samples.forEach((point, index) => {
        const [x, y] = hexToPixel(point.q, point.r, hexSize)
        if (index === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      })
      ctx.stroke()
    }
    ctx.restore()
  }
  if (editMode && selectedPathId) {
    const selected = queued.find((item) => item.path.id === selectedPathId || item.path.client_id === selectedPathId)
    if (selected) {
      selected.nodes.forEach((node, index) => {
        const [x, y] = hexToPixel(node.q, node.r, hexSize)
        ctx.beginPath()
        ctx.arc(x, y, Math.max(3, hexSize * 0.12), 0, Math.PI * 2)
        ctx.fillStyle = index === selectedNodeIndex ? "#F59E0B" : "#FFFFFF"
        ctx.fill()
        ctx.strokeStyle = "#1D4ED8"
        ctx.lineWidth = Math.max(1, hexSize * 0.05)
        ctx.stroke()
      })
    }
  }
  return queued
}

export function hitTestPath(paths, allNodes, q, r, tolerance = 0.25, geometryCache = null) {
  let best = null
  for (const path of paths || []) {
    if (path.visible === false || path.status === "archived") continue
    const nodes = pathNodesFor(path, allNodes)
    const cacheKey = `${path.id || path.client_id}:${path.content_revision || 0}`
    let samples = geometryCache?.get(cacheKey)
    if (!samples) {
      samples = samplePathGeometry(nodes)
      geometryCache?.set(cacheKey, samples)
    }
    for (let index = 0; index < samples.length - 1; index += 1) {
      const distance = Math.sqrt(pointDistanceSq({ q, r }, samples[index], samples[index + 1]))
      if (distance <= tolerance && (!best || distance < best.distance)) best = { path, distance }
    }
  }
  return best?.path || null
}

export function representativePathPoint(path, allNodes = []) {
  const nodes = pathNodesFor(path, allNodes)
  if (!nodes.length) return null
  if (nodes.length === 1) return { q: nodes[0].q, r: nodes[0].r }
  const lengths = []
  let total = 0
  for (let index = 0; index < nodes.length - 1; index += 1) {
    const length = Math.hypot(nodes[index + 1].q - nodes[index].q, nodes[index + 1].r - nodes[index].r)
    lengths.push(length)
    total += length
  }
  let remaining = total / 2
  for (let index = 0; index < lengths.length; index += 1) {
    if (remaining <= lengths[index]) {
      const t = lengths[index] ? remaining / lengths[index] : 0
      return {
        q: nodes[index].q + (nodes[index + 1].q - nodes[index].q) * t,
        r: nodes[index].r + (nodes[index + 1].r - nodes[index].r) * t,
      }
    }
    remaining -= lengths[index]
  }
  return { q: nodes.at(-1).q, r: nodes.at(-1).r }
}
