/**
 * 地图深链接构建/解析工具。
 */

const MAP_MODES = new Set(["overview", "recent", "dashboard", "live", "lens"])

export function normalizeMapMode(mode, { hasMap = false } = {}) {
  if (mode === "map") return "live"
  if (MAP_MODES.has(mode)) return mode
  return hasMap ? "dashboard" : "overview"
}

function finiteCoordinate(params, name) {
  if (!params.has(name)) return null
  const raw = params.get(name)
  if (raw == null || raw.trim() === "") return null
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

export function buildMapUrl({
  projectId,
  mapId = null,
  sceneId = null,
  focusEntityId = null,
  focusHexQ = null,
  focusHexR = null,
  focusPathId = null,
  focusLayerNodeId = null,
  mode = "overview",
} = {}) {
  const base = projectId ? `#workbench/${encodeURIComponent(projectId)}/map` : "#map"
  const params = new URLSearchParams()
  if (mapId) params.set("map_id", mapId)
  if (sceneId) params.set("scene_id", sceneId)
  if (focusEntityId) params.set("focus_entity_id", focusEntityId)
  if (focusHexQ != null) params.set("focus_hex_q", String(focusHexQ))
  if (focusHexR != null) params.set("focus_hex_r", String(focusHexR))
  if (focusPathId) params.set("focus_path_id", focusPathId)
  if (focusLayerNodeId) params.set("focus_layer_node_id", focusLayerNodeId)
  params.set("mode", normalizeMapMode(mode, { hasMap: Boolean(mapId) }))
  const query = params.toString()
  return query ? `${base}?${query}` : base
}

export function buildMapQuery(options = {}) {
  const url = buildMapUrl(options)
  return new URLSearchParams(url.split("?")[1] || "")
}

export function parseMapRouteContext(hash = window.location.hash) {
  const raw = (hash || "").replace(/^#/, "")
  const [path, query = ""] = raw.split("?")
  const parts = path.split("/")
  const params = new URLSearchParams(query)
  const isWorkbench = parts[0] === "workbench"
  return {
    projectId: isWorkbench ? decodeURIComponent(parts[1] || "") : null,
    mapId: params.get("map_id"),
    sceneId: params.get("scene_id"),
    focusEntityId: params.get("focus_entity_id"),
    focusHexQ: finiteCoordinate(params, "focus_hex_q"),
    focusHexR: finiteCoordinate(params, "focus_hex_r"),
    focusPathId: params.get("focus_path_id"),
    focusLayerNodeId: params.get("focus_layer_node_id"),
    mode: normalizeMapMode(params.get("mode"), { hasMap: Boolean(params.get("map_id")) }),
  }
}
