const REQUIRED_INTERACTIVE_CONDITIONS = Object.freeze([
  "state_ready",
  "leaflet_ready",
  "canvas_frame",
  "labels_ready",
  "handlers_ready",
])

const FRAME_WARMUP_COUNT = 20
const FRAME_SAMPLE_COUNT = 100
const SAFE_ROUTE_PARAMS = Object.freeze(new Set([
  "map_id",
  "mode",
  "scene_id",
  "focus_entity_id",
  "focus_hex_q",
  "focus_hex_r",
  "focus_path_id",
  "focus_layer_node_id",
]))

let activeSession = null
let longTaskObserver = null

function now() {
  return globalThis.performance?.now?.() ?? Date.now()
}

function finite(value, fallback = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function percentileNearestRank(values, percentile) {
  if (!Array.isArray(values) || values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const rank = Math.max(1, Math.ceil(sorted.length * percentile))
  return sorted[Math.min(sorted.length - 1, rank - 1)]
}

function average(values) {
  if (!Array.isArray(values) || values.length === 0) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function deepFreeze(value) {
  if (!value || typeof value !== "object" || Object.isFrozen(value)) return value
  Object.freeze(value)
  for (const child of Object.values(value)) deepFreeze(child)
  return value
}

function frozenClone(value) {
  const clone = typeof structuredClone === "function"
    ? structuredClone(value)
    : JSON.parse(JSON.stringify(value))
  return deepFreeze(clone)
}

function sanitizedMapRoute(route) {
  if (route == null) return null
  const raw = String(route)
  const [path, query = ""] = raw.split("?", 2)
  if (!query) return path
  const safeParams = new URLSearchParams()
  const params = new URLSearchParams(query)
  for (const [name, value] of params) {
    if (SAFE_ROUTE_PARAMS.has(name)) safeParams.append(name, value)
  }
  const safeQuery = safeParams.toString()
  return safeQuery ? `${path}?${safeQuery}` : path
}

function dispatch(name, detail) {
  if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") return
  window.dispatchEvent(new CustomEvent(name, { detail: frozenClone(detail) }))
}

function stopLongTaskObserver() {
  longTaskObserver?.disconnect?.()
  longTaskObserver = null
}

function startLongTaskObserver(sessionId) {
  stopLongTaskObserver()
  if (typeof PerformanceObserver !== "function") return
  try {
    longTaskObserver = new PerformanceObserver((list) => {
      if (!activeSession || activeSession.id !== sessionId) return
      for (const entry of list.getEntries()) {
        if (finite(entry.startTime, -1) < activeSession.navigationStartedAt) continue
        activeSession.longTasks.push({
          start_ms: finite(entry.startTime),
          duration_ms: finite(entry.duration),
        })
      }
    })
    longTaskObserver.observe({ type: "longtask", buffered: true })
  } catch {
    stopLongTaskObserver()
  }
}

function snapshot(session = activeSession) {
  if (!session) return null
  const frameDurations = session.frameDurations
  const inputDurations = session.inputDurations
  return {
    telemetry_id: session.id,
    map_id: session.mapId,
    grid: session.grid,
    route: session.route,
    navigation_started_at_ms: session.navigationStartedAt,
    emitted_at_ms: now(),
    interactive_ms: session.interactiveAt == null
      ? null
      : session.interactiveAt - session.navigationStartedAt,
    stages: { ...session.stages },
    conditions: { ...session.conditions },
    payload_bytes: session.payloadBytes,
    frames: {
      total: session.totalFrames,
      warmup: FRAME_WARMUP_COUNT,
      sampled: frameDurations.length,
      average_redraw_cpu_ms: average(frameDurations),
      p95_redraw_cpu_ms: percentileNearestRank(frameDurations, 0.95),
      raw_redraw_cpu_ms: [...frameDurations],
    },
    input: {
      sampled: inputDurations.length,
      average_to_paint_ms: average(inputDurations),
      p95_to_paint_ms: percentileNearestRank(inputDurations, 0.95),
      clicked_hex: session.clickedHex,
      types: { ...session.inputTypes },
      raw_to_paint_ms: [...inputDurations],
    },
    long_tasks: session.longTasks.map((entry) => ({ ...entry })),
  }
}

function maybeDispatchInteractive(session = activeSession) {
  if (!session || session.interactiveEmitted) return
  const ready = REQUIRED_INTERACTIVE_CONDITIONS.every((name) => session.conditions[name] != null)
  if (!ready) return
  session.interactiveAt = now()
  session.interactiveEmitted = true
  dispatch("map:interactive", snapshot(session))
}

function maybeDispatchPerformanceSample(session = activeSession) {
  if (!session || session.performanceSampleEmitted) return
  if (session.frameDurations.length < FRAME_SAMPLE_COUNT) return
  session.performanceSampleEmitted = true
  dispatch("map:performance-sample", snapshot(session))
}

export function beginMapNavigation({ mapId = null, route = null, startedAt = null } = {}) {
  const pendingNavigation = globalThis.__mapTelemetryPendingNavigation || null
  const queued = pendingNavigation?.mapId === mapId ? pendingNavigation : null
  if (queued) delete globalThis.__mapTelemetryPendingNavigation
  const requestedStart = startedAt ?? queued?.startedAt
  const navigationStartedAt = typeof requestedStart === "number" && Number.isFinite(requestedStart)
    ? requestedStart
    : now()
  const id = globalThis.crypto?.randomUUID?.()
    || `map-telemetry-${Date.now()}-${Math.random().toString(16).slice(2)}`
  activeSession = {
    id,
    mapId,
    grid: null,
    route: sanitizedMapRoute(route || queued?.route || null),
    navigationStartedAt,
    stageStarts: {},
    stages: {},
    conditions: {},
    payloadBytes: null,
    totalFrames: 0,
    frameDurations: [],
    inputDurations: [],
    pendingInputs: [],
    inputTypes: {},
    clickedHex: false,
    longTasks: [],
    interactiveAt: null,
    interactiveEmitted: false,
    performanceSampleEmitted: false,
  }
  try {
    performance.mark("map-nav-start", { detail: { telemetry_id: id, map_id: mapId } })
  } catch {
    // Older browsers may not support mark detail. The telemetry session remains valid.
  }
  startLongTaskObserver(id)
  return id
}

export function queueMapNavigationStart({ mapId = null, route = null, startedAt = null } = {}) {
  if (!mapId) {
    delete globalThis.__mapTelemetryPendingNavigation
    return null
  }
  const requestedStart = typeof startedAt === "number" && Number.isFinite(startedAt)
    ? startedAt
    : now()
  globalThis.__mapTelemetryPendingNavigation = {
    mapId,
    route: sanitizedMapRoute(route),
    startedAt: requestedStart,
  }
  return requestedStart
}

export function setMapTelemetryMetadata({ mapId, grid, payloadBytes } = {}) {
  if (!activeSession) return
  if (mapId != null) activeSession.mapId = mapId
  if (grid != null) activeSession.grid = String(grid)
  if (Number.isFinite(Number(payloadBytes))) activeSession.payloadBytes = Number(payloadBytes)
}

export function startMapTelemetryStage(name) {
  if (!activeSession || !name) return
  activeSession.stageStarts[name] = now()
}

export function endMapTelemetryStage(name, { durationMs = null } = {}) {
  if (!activeSession || !name) return
  if (activeSession.stages[name] != null) return
  const startedAt = activeSession.stageStarts[name]
  const duration = typeof durationMs === "number" && Number.isFinite(durationMs)
    ? durationMs
    : startedAt == null ? 0 : now() - startedAt
  activeSession.stages[name] = Math.max(0, duration)
  delete activeSession.stageStarts[name]
}

export function markMapTelemetryCondition(name) {
  if (!activeSession || !name || activeSession.conditions[name] != null) return
  activeSession.conditions[name] = Math.max(0, now() - activeSession.navigationStartedAt)
  maybeDispatchInteractive(activeSession)
}

export function recordMapInput(type, { clickedHex = false } = {}) {
  if (!activeSession) return
  const normalizedType = String(type || "unknown")
  activeSession.inputTypes[normalizedType] = (activeSession.inputTypes[normalizedType] || 0) + 1
  activeSession.clickedHex = activeSession.clickedHex || Boolean(clickedHex)
  activeSession.pendingInputs.push({ type: normalizedType, startedAt: now() })
  if (activeSession.pendingInputs.length > 8) activeSession.pendingInputs.shift()
}

export function recordMapFrame(redrawCpuMs, { nonEmpty = true } = {}) {
  if (!activeSession) return
  const finishedAt = now()
  const duration = Math.max(0, finite(redrawCpuMs))
  activeSession.totalFrames += 1
  if (nonEmpty) markMapTelemetryCondition("canvas_frame")
  if (activeSession.totalFrames > FRAME_WARMUP_COUNT && activeSession.frameDurations.length < FRAME_SAMPLE_COUNT) {
    activeSession.frameDurations.push(duration)
  }
  if (activeSession.pendingInputs.length) {
    const pending = activeSession.pendingInputs.at(-1)
    activeSession.pendingInputs = []
    if (activeSession.inputDurations.length < FRAME_SAMPLE_COUNT) {
      activeSession.inputDurations.push(Math.max(0, finishedAt - pending.startedAt))
    }
  }
  maybeDispatchPerformanceSample(activeSession)
}

export function cancelMapTelemetry() {
  activeSession = null
  stopLongTaskObserver()
}

export const MAP_TELEMETRY_LIMITS = Object.freeze({
  frameWarmupCount: FRAME_WARMUP_COUNT,
  frameSampleCount: FRAME_SAMPLE_COUNT,
})

export { percentileNearestRank }
