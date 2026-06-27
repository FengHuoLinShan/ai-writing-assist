/**
 * 地图深链接构建/解析工具。
 */

export function buildMapUrl({
  projectId,
  mapId = null,
  sceneId = null,
  focusEntityId = null,
  mode = "overview",
} = {}) {
  const base = projectId ? `#workbench/${encodeURIComponent(projectId)}/map` : "#map"
  const params = new URLSearchParams()
  if (mapId) params.set("map_id", mapId)
  if (sceneId) params.set("scene_id", sceneId)
  if (focusEntityId) params.set("focus_entity_id", focusEntityId)
  if (mode) params.set("mode", mode)
  const query = params.toString()
  return query ? `${base}?${query}` : base
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
    mode: params.get("mode") || "overview",
  }
}
