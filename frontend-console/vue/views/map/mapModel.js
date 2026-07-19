import { getApi, getAppState } from "../../bridge/index.js"
import { parseMapRouteContext } from "../../../views/mapRouteContext.js"

export const MAP_INBOX_PAGE_SIZE = 20
export const MAP_BATCH_ID_LIMIT = 100
export const ARCHIVED_PAGE_SIZE = 20
export const RECENT_PREFIX = "novel_map_recent:"

export const DEFAULT_MAP_LAYERS = Object.freeze({
  terrain: true,
  locations: true,
  markers: true,
  events: true,
  items: true,
  territories: true,
  candidate: false,
})

export const MAP_LAYER_LABELS = Object.freeze({
  terrain: "地形",
  locations: "地点",
  markers: "人物",
  events: "事件",
  items: "物品",
  territories: "势力",
  candidate: "待处理",
})

export function createMapInboxFilters() {
  return { dynamicType: "", sceneId: "", source: "", confidence: "", eligibility: "" }
}

export function listItems(data) {
  return Array.isArray(data?.items) ? data.items : Array.isArray(data) ? data : []
}

async function listAll(fetchPage, limit) {
  const output = []
  let skip = 0
  while (true) {
    const response = await fetchPage(skip, limit)
    const page = listItems(response)
    output.push(...page)
    if (!page.length || page.length < limit) return output
    skip += page.length
  }
}

export function recentMapKey(projectId) {
  return `${RECENT_PREFIX}${projectId || "none"}`
}

export function readRecentMap(projectId) {
  if (!projectId) return null
  try {
    const raw = localStorage.getItem(recentMapKey(projectId))
    return raw ? JSON.parse(raw) : null
  } catch {
    localStorage.removeItem(recentMapKey(projectId))
    return null
  }
}

export function saveRecentMap(projectId, map) {
  if (!projectId || !map?.id) return false
  localStorage.setItem(recentMapKey(projectId), JSON.stringify({
    mapId: map.id,
    name: map.name,
    mapType: map.map_type,
    openedAt: new Date().toISOString(),
  }))
  return true
}

export function clearRecentMap(projectId) {
  localStorage.removeItem(recentMapKey(projectId))
}

export function inboxSourceLabel(item = {}) {
  const source = item.source || item.source_ref?.source || item.source_ref?.workflow || ""
  return {
    deep_import: "深度导入",
    deep_import_delta_event: "深度导入",
    entity_created: "对象抽取",
    relation_created: "关系抽取",
    manual: "人工录入",
  }[source] || source || "来源已保留"
}

export function proposalTypeLabel(item = {}) {
  return {
    character_location: "人物位置",
    event_location: "事件位置",
    route_state: "线路状态",
    boundary: "势力范围",
    location: "位置建议",
    entity_created: "对象位置建议",
    entity_updated: "对象位置建议",
    relation_created: "关系位置建议",
    relation_updated: "关系位置建议",
  }[item.proposal_type || item.dynamic_type] || item.dynamic_type || "地图建议"
}

export function inboxEvidenceText(item = {}) {
  const raw = item.evidence_text || item.proposal_value?.area_description
    || item.proposal_value?.location_name || item.proposal_value?.path_name || ""
  return String(raw).replace(/^(?:deep_import_delta_event|entity_created|relation_created)\s*[\xB7:\uFF1A-]\s*/, "").trim()
    || "尚无可读的空间证据；可查看诊断信息或忽略此建议。"
}

export function inboxMissingLabels(item = {}) {
  const hasScene = item.scene_id || item.scene_index != null || item.time_anchor?.scene_index != null
  const hasChapter = item.source_chapter_id || item.source_chapter_index != null
  return (item.eligibility?.missing_item_labels || []).filter((label) => {
    const normalized = String(label || "").toLowerCase()
    if (hasScene && (normalized.includes("scene") || normalized.includes("场景"))) return false
    if (hasChapter && (normalized.includes("chapter") || normalized.includes("章节"))) return false
    return true
  }).map((label) => String(label).includes("未选择地图") ? "选择目标地图" : String(label).includes("动态字段尚未解析完整") ? "补全空间字段" : label)
}

export function inboxConfidenceLabel(item = {}) {
  if (item.confidence == null) return "置信度未提供"
  const value = Number(item.confidence)
  return Number.isFinite(value) ? `${Math.round(value * 100)}%` : "置信度未提供"
}

export function inboxTimeLabel(item = {}) {
  const parts = []
  const sceneIndex = item.scene_index ?? item.time_anchor?.scene_index
  if (sceneIndex != null) parts.push(`Scene ${Number(sceneIndex) + 1}`)
  else if (item.scene_id) parts.push("已关联 Scene")
  if (item.source_chapter_index != null) parts.push(`第 ${item.source_chapter_index} 章`)
  if (item.time_anchor?.kind === "initial_state") parts.push("初始状态")
  return parts.join(" · ") || item.time_label || "时间来源待补全"
}

export function filterInboxItems(items, filters = {}) {
  return (items || []).filter((item) => {
    const source = item.source || item.source_ref?.source || item.source_ref?.workflow || ""
    if (filters.source && source !== filters.source) return false
    if (filters.confidence === "low" && Number(item.confidence ?? 1) >= 0.6) return false
    if (filters.confidence === "high" && Number(item.confidence ?? 0) < 0.6) return false
    if (filters.eligibility === "ready" && !item.eligibility?.can_confirm) return false
    if (filters.eligibility === "missing" && item.eligibility?.can_confirm) return false
    return true
  })
}

export async function loadMapProps() {
  const api = getApi()
  const projectId = getAppState()?.currentProjectId || null
  const hash = typeof window === "undefined" ? "" : window.location.hash
  const route = parseMapRouteContext(hash)
  const filters = createMapInboxFilters()
  if (!projectId || !api?.world) return { projectId, route, maps: [], archivedMaps: [], locations: [], inbox: { items: [], total: 0, hasMore: false, page: 0, filters } }
  const [maps, archivedMaps, locations, inboxResult] = await Promise.all([
    listAll((skip, limit) => api.world.listMaps({ novel_id: projectId, status: "active", skip, limit }), 500),
    listAll((skip, limit) => api.world.listMaps({ novel_id: projectId, status: "archived", skip, limit }), 500),
    listAll((skip, limit) => api.world.listEntities({ novel_id: projectId, entity_type: "location", skip, limit }), 50),
    Promise.resolve(api.world.listProjectMapObservationInbox(projectId, { ...filters, skip: 0, limit: MAP_INBOX_PAGE_SIZE })).catch((error) => ({ error })),
  ])
  return {
    projectId,
    route,
    maps,
    archivedMaps,
    locations,
    inbox: {
      loading: false,
      items: listItems(inboxResult),
      total: Number(inboxResult?.total || 0),
      hasMore: Boolean(inboxResult?.has_more),
      error: inboxResult?.error?.message || null,
      page: 0,
      filters,
    },
  }
}
